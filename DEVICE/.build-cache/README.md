# DEVICE 构建依赖缓存

| 路径 | 用途 |
|------|------|
| `m2/repository/` | Maven 依赖（`docker build --build-context maven-repo=此目录`，二次构建复用） |

构建成功后 `du -sh m2/repository` 通常为数百 MB～数 GB，目录下有 `com/`、`org/` 等。
| `../target/jars/` | 编译好的 Jar（第一阶段提取，第二阶段 COPY） |

## 构建流程

```bash
./install_linux.sh install   # 强制两阶段 + 启动
./install_linux.sh update    # 强制两阶段 + 重启
./install_linux.sh build-base  # 仅 Maven 编译
./install_linux.sh build       # 两阶段（有缓存则跳过）
```

属主默认 `1000:1000`（`BUILD_CACHE_UID` 可覆盖）。
