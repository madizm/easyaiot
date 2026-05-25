package com.basiclab.iot.message.consumer;

import com.basiclab.iot.message.domain.model.AlertNotificationMessage;
import com.basiclab.iot.message.service.AlertNotificationService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.kafka.support.Acknowledgment;
import org.springframework.kafka.support.KafkaHeaders;
import org.springframework.messaging.handler.annotation.Header;
import org.springframework.messaging.handler.annotation.Payload;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Map;

/**
 * 告警通知Kafka消费者（iot-message服务）
 * 只负责：发送告警通知
 * 
 * 注意：告警存储和图片上传已移到iot-sink服务处理
 *
 * @author 翱翔的雄库鲁
 * @email andywebjava@163.com
 * @wechat EasyAIoT2025
 */
@Slf4j
@Component
public class AlertNotificationConsumer {

    @Autowired
    private AlertNotificationService alertNotificationService;

    /**
     * 消费告警通知消息（从iot-alert-notification-send主题）
     * 该主题的消息已经由iot-sink服务处理了存储和上传，这里只负责发送通知
     *
     * @param message 告警通知消息（Spring Kafka会自动反序列化为对象）
     * @param topic Kafka主题
     * @param partition 分区
     * @param offset 偏移量
     * @param acknowledgment Kafka确认机制
     */
    @KafkaListener(
            topics = "${spring.kafka.alert-notification.send-topic:iot-alert-notification-send}",
            groupId = "${spring.kafka.alert-notification.send-group-id:iot-message-alert-notification-consumer}"
    )
    public void consumeAlertNotification(
            @Payload AlertNotificationMessage message,
            @Header(KafkaHeaders.RECEIVED_TOPIC) String topic,
            @Header(KafkaHeaders.RECEIVED_PARTITION_ID) int partition,
            @Header(KafkaHeaders.OFFSET) long offset,
            Acknowledgment acknowledgment) {
        
        try {
            log.info("收到告警通知消息: topic={}, partition={}, offset={}, deviceId={}, alertId={}, taskId={}, taskName={}", 
                    topic, partition, offset, 
                    message != null ? message.getDeviceId() : null,
                    message != null ? message.getAlertId() : null,
                    message != null ? message.getTaskId() : null,
                    message != null ? message.getTaskName() : null);
            
            if (message == null) {
                log.error("告警通知消息为空");
                if (acknowledgment != null) {
                    acknowledgment.acknowledge();
                }
                return;
            }
            
            // 检查是否有通知配置
            List<Map<String, Object>> channels = message.getChannels();
            List<Map<String, Object>> notifyUsers = message.getNotifyUsers();
            List<String> notifyMethods = message.getNotifyMethods();
            Boolean shouldNotify = message.getShouldNotify();
            
            boolean hasNotificationConfig = hasAlertNotificationConfig(channels, notifyUsers);
            
            // 优先使用shouldNotify字段，如果没有则根据配置判断
            if (shouldNotify == null) {
                shouldNotify = hasNotificationConfig;
            }
            
            log.info("📊 告警通知配置信息: deviceId={}, alertId={}, shouldNotify={}, " +
                    "hasNotificationConfig={}, channels数量={}, notifyUsers数量={}, notifyMethods={}", 
                    message.getDeviceId(), message.getAlertId(), shouldNotify, hasNotificationConfig,
                    (channels != null ? channels.size() : 0),
                    (notifyUsers != null ? notifyUsers.size() : 0),
                    notifyMethods);
            
            if (!shouldNotify || !hasNotificationConfig) {
                log.info("ℹ️  告警消息中没有通知配置或shouldNotify=false，跳过发送通知: " +
                        "deviceId={}, alertId={}, shouldNotify={}, channels数量={}, notifyUsers数量={}", 
                        message.getDeviceId(), message.getAlertId(), shouldNotify,
                        (channels != null ? channels.size() : 0),
                        (notifyUsers != null ? notifyUsers.size() : 0));
                // 没有通知配置，直接确认消息
                if (acknowledgment != null) {
                    acknowledgment.acknowledge();
                }
                return;
            }
            
            // 发送告警通知
            try {
                log.info("📤 开始处理告警通知: alertId={}, deviceId={}, notifyUsers数量={}, notifyMethods={}", 
                        message.getAlertId(), message.getDeviceId(),
                        (notifyUsers != null ? notifyUsers.size() : 0),
                        notifyMethods);
                
                alertNotificationService.processAlertNotification(message);
                
                log.info("✅ 告警通知发送成功: alertId={}, deviceId={}, notifyUsers数量={}, notifyMethods={}", 
                        message.getAlertId(), message.getDeviceId(),
                        (notifyUsers != null ? notifyUsers.size() : 0),
                        notifyMethods);
            } catch (Exception e) {
                log.error("❌ 发送告警通知失败: alertId={}, deviceId={}, error={}", 
                        message.getAlertId(), message.getDeviceId(), e.getMessage(), e);
                // 通知发送失败不影响消息确认
            }
            
            // 确认消息已处理
            if (acknowledgment != null) {
                acknowledgment.acknowledge();
            }
            
        } catch (Exception e) {
            log.error("处理告警通知消息失败: deviceId={}, error={}", 
                    message != null ? message.getDeviceId() : null, e.getMessage(), e);
            // 注意：这里不确认消息，让Kafka重新投递，或者可以配置死信队列
            // 如果确认消息，错误消息会被丢弃
            // if (acknowledgment != null) {
            //     acknowledgment.acknowledge();
            // }
        }
    }

    private static boolean hasAlertNotificationConfig(
            List<Map<String, Object>> channels,
            List<Map<String, Object>> notifyUsers) {
        if (channels == null || channels.isEmpty()) {
            return false;
        }
        if (notifyUsers != null && !notifyUsers.isEmpty()) {
            return true;
        }
        return channels.stream().anyMatch(ch -> {
            Object method = ch.get("method");
            if (method == null) {
                return false;
            }
            String m = method.toString().toLowerCase();
            return "http".equals(m) || "webhook".equals(m);
        });
    }
}

