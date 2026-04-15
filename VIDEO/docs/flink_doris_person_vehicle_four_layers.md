# 人/车数据 Flink + Doris 四层大数据架构（可落地实现方案）

本文档面向 **VIDEO 侧产生的结构化检测/轨迹事件**（人、车、ReID、车牌、设备与时间），给出 **ODS → DWD → DWS → ADS** 四层在 **Apache Flink** 与 **Apache Doris** 上的具体落地方案：包含 **Kafka Topic 规划、Flink SQL 作业形态、Doris 表模型与导入方式、关键归因/串联算法在流上的实现要点**。

> **推荐组件版本（生产常用组合，可按你们基线调整）**  
> - Flink：1.17+（支持 `kafka`、`upsert-kafka`、`doris-connector` 生态成熟）  
> - Doris：2.0+（主键模型/部分列更新、Routine Load、物化视图）  
> - Kafka：3.x  

---

## 0. 数据域与 ID 体系（先定契约，再建四层）

### 0.1 事件类型（建议统一为「事实表行」）

| 事件类型 | 说明 | 最小字段 |
|---------|------|---------|
| `person_detection` | 人体检测框 | `event_id, device_id, ts, track_id, bbox, score, frame_no` |
| `vehicle_detection` | 车辆检测框 | 同上 + `vehicle_type` |
| `person_reid` | 人体 ReID 向量或特征 ID | `event_id, device_id, ts, track_id, reid_id, reid_score` |
| `plate_ocr` | 车牌识别 | `event_id, device_id, ts, track_id, plate_no, plate_score, plate_color` |
| `geo_fence`（可选） | 地理围栏/区域 ID | `device_id, ts, region_id` |

### 0.2 全局键（归因与串联的核心）

- **`event_id`**：UUID，幂等写入与重放去重。  
- **`device_id`**：摄像头/边缘盒子 ID（与现有 VIDEO 模块一致）。  
- **`ts`**：事件时间（毫秒），**必须**用于水印与窗口；接入时间放 `ingest_ts`。  
- **`track_id`**：单路视频内短期跟踪 ID（算法产生，可能断裂）。  
- **`global_person_id` / `global_vehicle_id`**：在 **DWD 层** 通过规则 + 图/状态生成的跨设备长期 ID（业务主键）。  

### 0.3 Kafka Topic 命名（示例）

```
ods.person_vehicle.raw          # VIDEO 服务直接写入的原始 JSON（或 Avro）
dwd.person_vehicle.event_std    # Flink 清洗后的标准行（可选，便于回放）
dws.person_vehicle.signal       # 宽表/会话中间信号（可选）
# ADS 通常不落 Kafka，直接查 Doris；如需推送告警可单独 topic
```

---

## 第一层：ODS（贴源层）——原始接入、保序、可重放

### 1.1 目标

- **原样保留** VIDEO 算法输出与设备元数据，支持 **合规审计、问题追溯、任务重放**。  
- **不做业务归因**，只做格式校验、必填字段补齐、分区键统一。

### 1.2 Doris 落地（建议 DUPLICATE + 分区）

**模型**：`DUPLICATE KEY`（append-only，吞吐最高，适合海量原始日志）。

```sql
CREATE TABLE IF NOT EXISTS ods_person_vehicle_raw (
    event_id        VARCHAR(64),
    event_type      VARCHAR(32),
    device_id       VARCHAR(64),
    ts              BIGINT,
    ingest_ts       BIGINT,
    payload         JSON,
    kafka_partition INT,
    kafka_offset    BIGINT
)
DUPLICATE KEY(event_id)
PARTITION BY RANGE (ts) ()
DISTRIBUTED BY HASH(device_id) BUCKETS 32
PROPERTIES (
    "replication_allocation" = "tag.location.default: 3",
    "enable_unique_key_merge_on_write" = "false"
);
-- 上线后通过 ADMIN 命令按天 add partition，例如按 ts 换算到日期分区
```

**导入方式（二选一或并存）**：

1. **Routine Load from Kafka**（最省事）：  
   - 消费 `ods.person_vehicle.raw`，JSON 解析到列，`event_id` 做去重在后续层处理（ODS 可不去重）。  
2. **Flink Doris Connector 流写**：适合已在 Flink 做复杂解析时直接写入。

**Kafka 消息体示例（VIDEO 服务写入）**：

```json
{
  "event_id": "uuid-...",
  "event_type": "person_detection",
  "device_id": "cam-001",
  "ts": 1710000000123,
  "payload": { "track_id": "t-12", "bbox": [100,200,50,80], "score": 0.91 }
}
```

### 1.3 Flink 落地（轻量校验作业 `job_ods_sanity`）

**职责**：读取 raw → 校验字段 → 写回「标准 ODS」或直写 Doris（若不在 Kafka 留副本）。

```sql
-- 伪代码：Flink SQL，实际表名与 catalog 按环境配置
CREATE TABLE kafka_raw (
  event_id STRING,
  event_type STRING,
  `device_id` STRING,
  `ts` BIGINT,
  payload STRING,
  proc_time AS PROCTIME()
) WITH (
  'connector' = 'kafka',
  'topic' = 'ods.person_vehicle.raw',
  'properties.bootstrap.servers' = '${KAFKA_BOOTSTRAP}',
  'properties.group.id' = 'flink_ods_sanity',
  'format' = 'json',
  'scan.startup.mode' = 'group-offsets'
);

CREATE TABLE kafka_ods_std WITH (
  'connector' = 'kafka',
  'topic' = 'ods.person_vehicle.std',
  ...
) LIKE kafka_raw;

INSERT INTO kafka_ods_std
SELECT event_id, event_type, device_id, ts, payload
FROM kafka_raw
WHERE event_id IS NOT NULL AND device_id IS NOT NULL AND ts > 0;
```

**运维要点**：  
- **保留周期**：ODS 表 7～30 天热数据 + 冷存（OSS/HDFS）归档 `payload` 原文。  
- **监控**：Kafka lag、Routine Load `ErrorLog`。

---

## 第二层：DWD（明细层）——标准化、去重、跨字段归因（人-车-牌-ReID）

### 2.1 目标

- **一行一事件** 或 **一行一 track 快照**（二选一，建议事件行 + 小时拉链补表）。  
- 产出 **`global_vehicle_id` / `global_person_id`** 的初版（可迭代）：  
  - 车：**车牌** 强绑定；无牌车用 **设备+轨迹特征+时间** 软绑定。  
  - 人：**ReID** 强绑定；无 ReID 用 **设备+track+时间** 软绑定。  
- **时间对齐**：同一 `device_id` 下车与人检测做 **Interval Join**（例如 ±300ms）。

### 2.2 Doris 落地

**2.2.1 明细事实表（UNIQUE 主键，便于幂等与状态修正）**

```sql
CREATE TABLE IF NOT EXISTS dwd_person_vehicle_event (
    event_id            VARCHAR(64),
    event_type          VARCHAR(32),
    device_id           VARCHAR(64),
    ts                  BIGINT,
    track_id            VARCHAR(64),
    global_person_id    VARCHAR(64),
    global_vehicle_id   VARCHAR(64),
    plate_no            VARCHAR(16),
    reid_id             VARCHAR(64),
    score               DOUBLE,
    attrs               JSON
)
UNIQUE KEY(event_id)
DISTRIBUTED BY HASH(device_id) BUCKETS 32
PROPERTIES (
    "enable_unique_key_merge_on_write" = "true"
);
```

**2.2.2 人-车关联宽表（可选，便于分析）**

```sql
CREATE TABLE IF NOT EXISTS dwd_person_vehicle_assoc (
    assoc_id            VARCHAR(64),
    device_id           VARCHAR(64),
    ts                  BIGINT,
    person_event_id     VARCHAR(64),
    vehicle_event_id    VARCHAR(64),
    relation_type       VARCHAR(16),  -- e.g. 'near', 'onboard_infer'
    confidence          DOUBLE
)
UNIQUE KEY(assoc_id)
DISTRIBUTED BY HASH(device_id) BUCKETS 32;
```

### 2.3 Flink 落地（核心作业 `job_dwd_attribution`）

**2.3.1 水印与事件时间**

```sql
CREATE TABLE person_det (
  event_id STRING,
  device_id STRING,
  ts BIGINT,
  track_id STRING,
  WATERMARK FOR ts AS ts - INTERVAL '2' SECOND
) WITH ('connector' = 'kafka', 'topic' = '...person...', ...);

CREATE TABLE vehicle_det ( ... ) LIKE person_det;
CREATE TABLE plate_ocr ( ... ) LIKE person_det;
```

**2.3.2 车 + 牌：先按 `device_id + track_id` 做窗口聚合，再合并车牌**

- 使用 **10s 滚动窗口** 或 **会话窗口（gap 5s）** 收集同一 track 下最高分的 `plate_no`。  
- 产出 `global_vehicle_id = md5(plate_no)`（有牌）；无牌则 `md5(device_id + track_session_id)`。

**2.3.3 人 + ReID：`global_person_id = reid_id`（有）否则 `md5(device_id + track_id + session)`**

**2.3.4 人-车空间邻近（落地规则示例）**

- 若算法输出 **bbox**：在 **KeyedProcessFunction** 中维护 `MapState<vehicle_track, bbox>` 与 `person_track`，计算 **IoU 或中心点距离 < 阈值** 且时间差 < 300ms → 写入 `dwd_person_vehicle_assoc`。  
- 若只有 **检测结果无几何**：退化为 **同设备同秒级共现**（置信度降低，写入 `confidence`）。

**写入 Doris**：  
- 使用 **Flink Doris Connector**（`doris.sink`）批量 `stream load`；`event_id` 作为幂等键。  
- 或 Flink 写 Kafka `dwd.*`，由 Doris **Routine Load** 消费（解耦更好）。

---

## 第三层：DWS（汇总层）——轨迹串联、会话、跨镜融合指标

### 3.1 目标

- **轨迹分段（trip/session）**：同一 `global_*_id` 下，时间间隔 > **T_gap（如 30min）** 或空间跳跃异常则新开 session。  
- **跨设备串联**：依赖 **ReID / 车牌 / 时间转移矩阵**（路口拓扑可后续增强）。  
- 产出 **小时/天级** 汇总：出现次数、首次/末次出现设备、路径熵、同行人等。

### 3.2 Doris 落地

**3.2.1 轨迹点聚合表（AGGREGATE 或 DUPLICATE + 物化视图）**

```sql
CREATE TABLE IF NOT EXISTS dws_trajectory_point_hour (
    stat_date           DATE,
    stat_hour           TINYINT,
    global_entity_id    VARCHAR(64),
    entity_type         VARCHAR(8),   -- 'person' / 'vehicle'
    device_id           VARCHAR(64),
    first_ts            BIGINT REPLACE,
    last_ts             BIGINT REPLACE,
    appear_cnt          BIGINT SUM
)
AGGREGATE KEY(stat_date, stat_hour, global_entity_id, entity_type, device_id)
PARTITION BY RANGE (stat_date) ()
DISTRIBUTED BY HASH(global_entity_id) BUCKETS 32;
```

**3.2.2 会话表（UNIQUE）**

```sql
CREATE TABLE IF NOT EXISTS dws_entity_session (
    session_id          VARCHAR(64),
    global_entity_id    VARCHAR(64),
    entity_type         VARCHAR(8),
    start_ts            BIGINT,
    end_ts              BIGINT,
    device_seq          JSON,
    path_signature      VARCHAR(256)
)
UNIQUE KEY(session_id)
DISTRIBUTED BY HASH(global_entity_id) BUCKETS 32;
```

**跨镜融合（Doris 侧离线补齐）**：  
- 定时 SQL（**INSERT INTO dws_... SELECT ...**）按 `global_entity_id` 合并多设备轨迹；或用 **物化视图** 维护小时rollup。

### 3.3 Flink 落地（作业 `job_dws_session`）

- **KeyedProcessFunction + ValueState**：  
  - `last_ts`, `current_session_id`, `device_list`  
  - 每条事件：`if (ts - last_ts > T_gap) { flush session; new session }`  
- **侧输出**：异常轨迹（时间倒流、设备跳变过大）到 **质检 topic**。  
- **输出**：  
  1. 实时写 `dws_entity_session`（Flink → Doris）；  
  2. 同时写 **Kafka changelog** 供下游实时大屏（可选）。

---

## 第四层：ADS（应用层）——面向 VIDEO/运营/告警的指标与接口表

### 4.1 目标

- **低延迟查询**（< 1s）：设备维度、区域维度、车辆维度。  
- **强约束字段类型**，便于 **WEB 大屏 / API**。  
- 与 **权限** 结合：按租户/项目行级过滤（可在同步任务或视图层做）。

### 4.2 Doris 落地

**示例：设备实时在线人车流量（分钟级）**

```sql
CREATE TABLE IF NOT EXISTS ads_device_flow_minute (
    stat_time           DATETIME,
    device_id           VARCHAR(64),
    person_in_cnt       BIGINT,
    vehicle_in_cnt      BIGINT,
    alert_cnt           BIGINT
)
DUPLICATE KEY(stat_time, device_id)
PARTITION BY RANGE (stat_time) ()
DISTRIBUTED BY HASH(device_id) BUCKETS 16;
```

**示例：重点车辆布控命中（车牌维度）**

```sql
CREATE TABLE IF NOT EXISTS ads_plate_watch_hit (
    stat_date           DATE,
    plate_no            VARCHAR(16),
    hit_cnt             BIGINT,
    last_device_id      VARCHAR(64),
    last_ts             BIGINT
)
UNIQUE KEY(stat_date, plate_no)
DISTRIBUTED BY HASH(plate_no) BUCKETS 8;
```

**从 DWS 刷新 ADS（调度）**：  
- 使用 **Doris Insert Job / 外部调度（Airflow / DolphinScheduler）** 每分钟/每小时执行聚合 SQL。  
- 或对 `dws_trajectory_point_hour` 建 **ROLLUP / 物化视图** 直接查询以降低 ADS 冗余。

### 4.3 Flink 落地（可选 `job_ads_realtime`）

- 若大屏要 **秒级**：Flink **滑动窗口 1min** 直接写 `ads_device_flow_minute`。  
- 若 **分钟级可接受**：仅用 Doris 定时任务更简单、运维成本更低。

---

## 端到端数据流（落地拓扑简图）

```
VIDEO 服务 --JSON--> Kafka(ods.raw)
        |                               \
        v                                --> Flink(job_ods_sanity) --> Kafka(ods.std) --> Routine Load --> Doris(ods_*)
        \-->（可选）Flink(job_dwd) ----------------------------------------> Doris(dwd_*)
                              \
                               v
                        Flink(job_dws_session) --> Doris(dws_*)
                              \
                               v
             DolphinScheduler / Doris Insert Job --> Doris(ads_*)
                              \
                               v
                          WEB / API / 告警
```

---

## 工程落地清单（按优先级）

| 顺序 | 任务 | 产出 |
|-----|------|------|
| 1 | VIDEO 写 Kafka 统一 Schema + `event_id` | 可重放日志 |
| 2 | Doris 建 ODS/DWD 表 + Routine Load | 可查可存 |
| 3 | Flink `job_dwd_attribution` 水印 + 车牌合并 + 人车间隔/几何关联 | `global_*_id`、assoc 表 |
| 4 | Flink `job_dws_session` 会话状态机 | `dws_entity_session` |
| 5 | 调度聚合 SQL + ADS 表 | 大屏与接口 |
| 6 | 监控：Flink Checkpoint、Kafka Lag、Doris Stream Load 错误率、数据延迟 P99 | SLA |

---

## 与现有 VIDEO 模块的衔接建议

- **接入点**：在现有算法回调或 `alert_hook` / Kafka 推送路径上，增加 **标准化 JSON 发送** 到 `ods.person_vehicle.raw`（与本文 0.1 字段对齐）。  
- **不要在 ODS 做重计算**：避免拖慢视频链路；归因放在 Flink 并行扩展。  
- **回放**：按 `event_id` + Kafka 时间戳重放，可验证归因规则迭代效果。

---

## 文档维护

- **路径**：`VIDEO/docs/flink_doris_person_vehicle_four_layers.md`  
- **变更记录**：随你们选定的 Flink/Doris 版本升级，调整 Connector 参数与 Doris 属性名。
