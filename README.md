# EasyAIoT (Cloud-Edge-Device Integrated Collaborative Algorithm Application Platform)

[![Gitee star](https://gitee.com/volara/easyaiot/badge/star.svg?theme=gvp)](https://gitee.com/soaring-xiongkulu/easyaiot/stargazers)
[![Gitee fork](https://gitee.com/volara/easyaiot/badge/fork.svg?theme=gvp)](https://gitee.com/soaring-xiongkulu/easyaiot/members)

<p style="font-size: 16px; line-height: 1.8; color: #555; font-weight: 400; margin: 20px 0;">
My vision is for this system to be accessible worldwide, achieving truly zero barriers to AI. Everyone should experience the benefits of AI, not just a privileged few.
</p>

<div align="center">
    <img src=".image/logo.png" width="30%" height="30%" alt="EasyAIoT">
</div>

<h4 align="center" style="display: flex; justify-content: center; gap: 20px; flex-wrap: wrap; padding: 20px; font-weight: bold;">
  <a href="./README.md">English</a>
  <span style="display: flex; align-items: center; color: #666; font-weight: bold;">|</span>
  <a href="./README_zh.md">简体中文</a>
  <span style="display: flex; align-items: center; color: #666; font-weight: bold;">|</span>
  <a href="./README_zh_tw.md">繁體中文</a>
  <span style="display: flex; align-items: center; color: #666; font-weight: bold;">|</span>
  <a href="./README_ru.md">Русский</a>
  <span style="display: flex; align-items: center; color: #666; font-weight: bold;">|</span>
  <a href="./README_fr.md">Français</a>
  <span style="display: flex; align-items: center; color: #666; font-weight: bold;">|</span>
  <a href="./README_ko.md">한국어</a>
</h4>

## 🌟 Some Thoughts on the Project

### 📍 Project Positioning

<p style="font-size: 15px; line-height: 1.8; color: #333; margin: 15px 0;">
EasyAIoT is a cloud-edge-device integrated intelligent IoT platform that focuses on the deep integration of AI and IoT. Through core capabilities such as algorithm task management, real-time stream analysis, and model service cluster inference, the platform achieves a complete closed-loop from device access to data collection, AI analysis, and intelligent decision-making, truly realizing interconnected everything and intelligent control of everything.
</p>

#### 🧠 AI Capabilities

<ul style="font-size: 14px; line-height: 1.8; color: #444; margin: 10px 0;">
  <li><strong>Multi-Protocol Camera Access Support</strong>: Comprehensive support for GB28181 and ONVIF, two mainstream video surveillance protocols, enabling standardized device access and management. GB28181, as China's national standard, perfectly adapts to mainstream domestic surveillance equipment; ONVIF, as an international universal standard, widely compatible with global mainstream camera brands. Through dual-protocol support, the platform seamlessly integrates with existing surveillance systems, achieving plug-and-play device access, automatic discovery, and unified management, significantly reducing device access barriers, enhancing system compatibility and scalability, and providing a solid technical foundation for large-scale camera deployment</li>
  <li><strong>Face Recognition and Face Library Management</strong>: Supports flexibly enabling face recognition in camera tasks. Built on Milvus for face library and facial feature vector management, it provides create/query/update/delete capabilities for face samples and feature vectors, as well as high-performance vector retrieval. It supports efficient face comparison and identity retrieval on captured frames, while fully recording match results, snapshots, camera location information, and device context for personnel trajectory tracing, security forensics, and multidimensional statistical analysis.</li>
  <li><strong>Vision Large Model Intelligent Understanding</strong>: Integrated with QwenVL3 vision large model, supports deep visual reasoning and semantic understanding of real-time video frames, enabling intelligent analysis and scene comprehension of frame content, providing richer visual cognitive capabilities, achieving a leap from pixel-level perception to semantic-level understanding</li>
  <li><strong>Real-Time Camera AI Analysis</strong>: Supports AI intelligent analysis of real-time camera feeds. Performs AI algorithm processing such as object detection, behavior analysis, and anomaly recognition on real-time video streams, providing millisecond-level response real-time analysis results, supporting concurrent analysis of multiple video streams</li>
  <li><strong>Cloud-Edge-Device Integrated Algorithm Alert Monitoring Dashboard</strong>: Provides a unified cloud-edge-device integrated algorithm alert monitoring dashboard that displays key information in real-time, including device status, algorithm task operations, alarm event statistics, and video stream analysis results. Supports multi-dimensional data visualization, achieving unified monitoring and management of cloud, edge, and device layers, providing decision-makers with a global perspective intelligent monitoring command center</li>
  <li><strong>Device Detection Region Drawing</strong>: Provides a visual device detection region drawing tool that supports drawing rectangular and polygonal detection regions on device snapshot images, supports flexible association configuration between regions and algorithm models, supports visual management, editing, and deletion of regions, supports keyboard shortcuts to improve drawing efficiency, enabling precise region detection configuration and providing accurate detection range definitions for algorithm tasks</li>
  <li><strong>Intelligent Linked Alert Mechanism</strong>: Supports a triple-link mechanism between detection regions, defense time periods, and event alerts. The system intelligently determines whether a detected event simultaneously meets the specified detection region range, falls within the defense time period, and matches the alert event type. Alerts are only triggered when all three conditions are met, achieving precise spatiotemporal condition filtering, significantly reducing false positive rates, and improving the accuracy and practicality of the alert system</li>
  <li><strong>Large-Scale Camera Management</strong>: Supports access to hundreds of cameras, providing end-to-end services including collection, annotation, training, inference, export, analysis, alerting, recording, storage, and deployment</li>
  <li><strong>Algorithm Task Management</strong>: Supports creation and management of two types of algorithm tasks, each task can flexibly bind frame extractors and sorters to achieve precise video frame extraction and result sorting
    <ul style="margin: 5px 0; padding-left: 20px;">
      <li><strong>Real-Time Algorithm Tasks</strong>: Used for real-time video analysis, supporting RTSP/RTMP stream real-time processing with millisecond-level response capabilities, suitable for monitoring, security, and other real-time scenarios</li>
      <li><strong>Snapshot Algorithm Tasks</strong>: Used for snapshot image analysis, performing intelligent recognition and analysis on captured images, suitable for event backtracking, image retrieval, and other scenarios</li>
    </ul>
  </li>
  <li><strong>Stream Forwarding</strong>: Supports direct viewing of camera real-time feeds without enabling AI analysis functionality. By creating stream forwarding tasks, multiple cameras can be batch-pushed, enabling synchronous viewing of multiple video streams to meet pure video monitoring scenario requirements</li>
  <li><strong>GPU Discovery, Load-Aware Allocation, and Multi-GPU Collaboration</strong>: The platform provides GPU resource discovery and intelligent scheduling: it detects the number of available GPUs and dynamically assigns video encode/decode and algorithm inference work across cards according to per-GPU load, running tasks in parallel where appropriate to raise multi-stream throughput and utilization while keeping the pipeline stable—coordinating frame processing and model inference in multi-GPU deployments</li>
  <li><strong>Smart Transport Selection and Resilient Stream Pull</strong>: On RTSP and similar pull paths, the system can evaluate URL/path and related signals to choose and switch transport-layer modes; camera pulls default to UDP for lower latency. When consecutive frames indicate gray screen, decode errors, or stream collapse (decode stall), RTSP reconnect and link recovery run automatically to limit prolonged artifacts or frozen video</li>
  <li><strong>Separate Viewing vs Algorithm Pipelines and Tiered Bitrates</strong>: Live preview and wall viewing are decoupled from algorithm analysis frame extraction in both data path and control policy, with two independent control planes. The viewing path uses about 6500 Kbps to prioritize sharp, smooth monitoring; the algorithm path uses about 3500 Kbps to balance detection quality with compute and bandwidth, avoiding analysis and viewing competing on one high-bitrate channel—so operators get clear, fluid video while analysis stays scalable</li>
  <li><strong>Model Service Cluster Inference</strong>: Supports distributed model inference service clusters, achieving intelligent load balancing, automatic failover, and high availability guarantees, significantly improving inference throughput and system stability</li>
  <li><strong>Defense Time Period Management</strong>: Supports two defense strategies: full defense mode and half defense mode, allowing flexible configuration of defense rules for different time periods, achieving precise time-based intelligent monitoring and alerting</li>
  <li><strong>OCR and Speech Recognition</strong>: High-precision text recognition based on PaddleOCR with speech-to-text functionality, providing multi-language recognition capabilities</li>
  <li><strong>Multimodal Vision Large Models</strong>: Supports various vision tasks including object recognition and text recognition, providing powerful image understanding and scene analysis capabilities</li>
  <li><strong>LLM Large Language Models</strong>: Supports intelligent analysis and understanding of multiple input formats including RTSP streams, video, images, audio, and text, achieving multimodal content understanding</li>
  <li><strong>Model Deployment and Version Management</strong>: Supports rapid deployment and version management of AI models, enabling one-click model deployment, version rollback, and gray release</li>
  <li><strong>Multi-Instance Management</strong>: Supports concurrent operation and resource scheduling of multiple model instances, improving system utilization and resource efficiency</li>
  <li><strong>Camera Snapshot</strong>: Supports real-time camera snapshot functionality with configurable snapshot rules and trigger conditions, achieving intelligent snapshot capture and event recording</li>
  <li><strong>Snapshot Storage Space Management</strong>: Provides storage space management for snapshot images with quota and cleanup policy support, ensuring rational utilization of storage resources</li>
  <li><strong>Video Storage Space Management</strong>: Provides storage space management for video files with automatic cleanup and archiving, achieving intelligent storage resource management</li>
  <li><strong>Snapshot Image Management</strong>: Supports full lifecycle management of snapshot images including viewing, searching, downloading, and deletion, providing convenient image management functionality</li>
  <li><strong>Device Directory Management</strong>: Provides hierarchical device directory management with device grouping, multi-level management, and permission control, achieving organized and fine-grained device management</li>
  <li><strong>Alarm Recording</strong>: Supports automatic recording triggered by alarm events. When abnormal events are detected, relevant video clips are automatically recorded, providing a complete alarm evidence chain. Supports viewing, downloading, and management of alarm recordings</li>
  <li><strong>Alarm Events</strong>: Provides comprehensive alarm event management functionality, supporting real-time alarm event push, historical query, statistical analysis, event processing, and status tracking, achieving full lifecycle management of alarms</li>
  <li><strong>Video Playback</strong>: Supports fast retrieval and playback of historical recordings, providing convenient operations such as timeline positioning, variable speed playback, and keyframe jumping. Supports synchronized playback of multiple video streams, meeting event backtracking and analysis needs</li>
</ul>

#### 🌐 IoT Capabilities

<ul style="font-size: 14px; line-height: 1.8; color: #444; margin: 10px 0;">
  <li><strong>Device Access and Management</strong>: Device registration, authentication, status monitoring, lifecycle management</li>
  <li><strong>Product and Thing Model Management</strong>: Product definition, thing model configuration, product management</li>
  <li><strong>Multi-Protocol Support</strong>: Multiple IoT protocols including MQTT, TCP, HTTP</li>
  <li><strong>Device Authentication and Dynamic Registration</strong>: Secure access, identity authentication, dynamic device registration</li>
  <li><strong>Rule Engine</strong>: Data flow rules, message routing, data transformation</li>
  <li><strong>Data Collection and Storage</strong>: Device data collection, storage, query, and analysis</li>
  <li><strong>Device Status Monitoring and Alert Management</strong>: Real-time monitoring, anomaly alerts, intelligent decision-making</li>
  <li><strong>Notification Management</strong>: Supports 7 notification methods including Feishu, DingTalk, Enterprise WeChat, Email, Tencent Cloud SMS, Alibaba Cloud SMS, and Webhook, enabling flexible and multi-channel alert notifications</li>
</ul>


### 💡 Technical Philosophy

<p style="font-size: 14px; line-height: 1.8; color: #555; margin: 15px 0;">
We believe no single programming language excels at everything, but through the deep integration of three programming languages, EasyAIoT leverages the strengths of each to build a powerful technical ecosystem.
</p>

<p style="font-size: 14px; line-height: 1.8; color: #555; margin: 15px 0;">
Java excels at building stable and reliable platform architectures but is not suitable for network programming and AI development; Python excels at network programming and AI algorithm development but has bottlenecks in high-performance task execution; C++ excels at high-performance task execution but is less suitable than the other two for platform development and AI programming. EasyAIoT adopts a tri-lingual mixed programming architecture, fully leveraging the strengths of each language to build an AIoT platform that's challenging to implement but extremely easy to use.
</p>

![EasyAIoT Platform Architecture.jpg](.image/iframe2.jpg)

### 🔄 Module Data Flow

<img src=".image/iframe3.jpg" alt="EasyAIoT Platform Architecture" style="max-width: 100%; height: auto; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">

### 🤖 Zero-Shot Labeling Technology

<p style="font-size: 14px; line-height: 1.8; color: #555; margin: 15px 0;">
Innovatively leveraging large models to construct a zero-shot labeling technical system (ideally completely eliminating manual labeling, achieving full automation of the labeling process), this technology generates initial data through large models and completes automatic labeling via prompt engineering. It then ensures data quality through optional human-machine collaborative verification, thereby training an initial small model. This small model, through continuous iteration and self-optimization, achieves co-evolution of labeling efficiency and model accuracy, ultimately driving continuous improvement in system performance.
</p>

<img src=".image/iframe4.jpg" alt="EasyAIoT Platform Architecture" style="max-width: 100%; height: auto; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">

### 🏗️ Project Architecture Features

<p style="font-size: 14px; line-height: 1.8; color: #555; margin: 15px 0;">
EasyAIoT is not actually one project; it is seven distinct projects.
</p>

<p style="font-size: 14px; line-height: 1.8; color: #555; margin: 15px 0;">
What's the benefit? Suppose you are on a resource-constrained device (like an RK3588). You can extract and independently deploy just one of those projects. Therefore, while this project appears to be a cloud platform, it simultaneously functions as an edge platform.
</p>

<div style="margin: 30px 0; padding: 20px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius: 10px; color: white;">

<p style="font-size: 16px; line-height: 1.8; margin: 0; font-weight: 500;">
🌟 Genuine open source is rare. If you find this project useful, please star it before leaving - your support means everything to us!<br>
<small style="font-size: 14px; opacity: 0.9;">(In an era where fake open-source projects are rampant, this project stands out as an exception.)</small>
</p>

</div>

### 🌍 Localization Support

<p style="font-size: 15px; line-height: 1.8; color: #333; margin: 15px 0;">
EasyAIoT actively responds to localization strategies, providing comprehensive support for localized hardware and operating systems, delivering secure and controllable AIoT solutions for users:
</p>

<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin: 20px 0;">

<div style="padding: 20px; background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); border-radius: 10px; color: white; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
<h4 style="margin-top: 0; color: white; font-size: 18px;">🖥️ Server-Side Support</h4>
<ul style="font-size: 14px; line-height: 1.8; margin: 10px 0; padding-left: 20px;">
  <li>Full compatibility with Hygon x86 architecture processors</li>
  <li>Support for localized server hardware platforms</li>
  <li>Targeted performance optimization solutions</li>
  <li>Ensures stable operation of enterprise applications</li>
</ul>
</div>

<div style="padding: 20px; background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%); border-radius: 10px; color: white; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
<h4 style="margin-top: 0; color: white; font-size: 18px;">📱 Edge-Side Support</h4>
<ul style="font-size: 14px; line-height: 1.8; margin: 10px 0; padding-left: 20px;">
  <li>Comprehensive support for Rockchip ARM architecture chips</li>
  <li>Perfect adaptation to mainstream edge computing platforms like RK3588</li>
  <li>Deep optimization for edge scenarios</li>
  <li>Enables lightweight deployment of edge intelligence</li>
</ul>
</div>

<div style="padding: 20px; background: linear-gradient(135deg, #43e97b 0%, #38f9d7 100%); border-radius: 10px; color: white; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
<h4 style="margin-top: 0; color: white; font-size: 18px;">🖱️ Operating System Support</h4>
<ul style="font-size: 14px; line-height: 1.8; margin: 10px 0; padding-left: 20px;">
  <li>Compatible with Kylin operating system</li>
  <li>Support for localized Linux distributions like Founder</li>
  <li>Adaptation to mainstream localized operating systems like UOS</li>
  <li>Provides complete localized deployment solutions</li>
</ul>
</div>

</div>

## 🎯 Application Scenarios

![Application Scenarios.png](.image/适用场景.png)

## 🧩 Project Structure

<p style="font-size: 15px; line-height: 1.8; color: #333; margin: 15px 0;">
EasyAIoT consists of five core projects:
</p>

<table style="width: 100%; border-collapse: collapse; margin: 20px 0; font-size: 14px;">
<tr>
<td style="padding: 15px; border: 1px solid #e0e0e0; background-color: #f8f9fa; font-weight: 600; color: #2c3e50; width: 20%;">Module</td>
<td style="padding: 15px; border: 1px solid #e0e0e0; background-color: #f8f9fa; font-weight: 600; color: #2c3e50;">Description</td>
</tr>
<tr>
<td style="padding: 15px; border: 1px solid #e0e0e0; vertical-align: top;"><strong>WEB Module</strong></td>
<td style="padding: 15px; border: 1px solid #e0e0e0; line-height: 1.8; color: #444;">Frontend management interface based on Vue, providing a unified user interaction experience</td>
</tr>
<tr>
<td style="padding: 15px; border: 1px solid #e0e0e0; vertical-align: top;"><strong>DEVICE Module</strong></td>
<td style="padding: 15px; border: 1px solid #e0e0e0; line-height: 1.8; color: #444;">
  <ul style="margin: 5px 0; padding-left: 20px;">
    <li><strong>Technical Advantages</strong>: Based on JDK21, providing better performance and modern features</li>
    <li><strong>Device Management</strong>: Device registration, authentication, status monitoring, lifecycle management</li>
    <li><strong>Product Management</strong>: Product definition, thing model management, product configuration</li>
    <li><strong>Protocol Support</strong>: Multiple IoT protocols including MQTT, TCP, HTTP</li>
    <li><strong>Device Authentication</strong>: Device dynamic registration, identity authentication, secure access</li>
    <li><strong>Rule Engine</strong>: Data flow rules, message routing, data transformation</li>
    <li><strong>Data Collection</strong>: Device data collection, storage, query, and analysis</li>
  </ul>
</td>
</tr>
<tr>
<td style="padding: 15px; border: 1px solid #e0e0e0; vertical-align: top;"><strong>VIDEO Module</strong></td>
<td style="padding: 15px; border: 1px solid #e0e0e0; line-height: 1.8; color: #444;">
  <ul style="margin: 5px 0; padding-left: 20px;">
    <li><strong>Stream Processing</strong>: Supports RTSP/RTMP stream real-time processing and transmission</li>
    <li><strong>Algorithm Task Management</strong>: Supports real-time algorithm tasks and snapshot algorithm tasks, used for real-time video analysis and snapshot image analysis respectively</li>
    <li><strong>Frame Extractor and Sorter</strong>: Supports flexible frame extraction strategies and result sorting mechanisms, each algorithm task can bind independent frame extractors and sorters</li>
    <li><strong>Defense Time Period</strong>: Supports time-based configuration for full defense mode and half defense mode</li>
  </ul>
</td>
</tr>
<tr>
<td style="padding: 15px; border: 1px solid #e0e0e0; vertical-align: top;"><strong>AI Module</strong></td>
<td style="padding: 15px; border: 1px solid #e0e0e0; line-height: 1.8; color: #444;">
  <ul style="margin: 5px 0; padding-left: 20px;">
    <li><strong>Intelligent Analysis</strong>: Responsible for video analysis and AI algorithm execution</li>
    <li><strong>Model Service Cluster</strong>: Supports distributed model inference services, achieving load balancing and high availability</li>
    <li><strong>Real-Time Inference</strong>: Provides millisecond-level response real-time intelligent analysis capabilities</li>
    <li><strong>Model Management</strong>: Supports model deployment, version management, and multi-instance scheduling</li>
  </ul>
</td>
</tr>
<tr>
<td style="padding: 15px; border: 1px solid #e0e0e0; vertical-align: top;"><strong>TASK Module</strong></td>
<td style="padding: 15px; border: 1px solid #e0e0e0; line-height: 1.8; color: #444;">C++-based high-performance task processing module responsible for compute-intensive task execution</td>
</tr>
</table>

## 🖥️ Cross-Platform Deployment Advantages

<p style="font-size: 15px; line-height: 1.8; color: #333; margin: 15px 0;">
EasyAIoT supports deployment on Linux, Mac, and Windows, providing flexible and convenient deployment solutions for users in different environments:
</p>

<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin: 20px 0;">

<div style="padding: 20px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius: 10px; color: white; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
<h4 style="margin-top: 0; color: white; font-size: 18px;">🐧 Linux Deployment Advantages</h4>
<ul style="font-size: 14px; line-height: 1.8; margin: 10px 0; padding-left: 20px;">
  <li>Ideal for production environments, stable and reliable with low resource consumption</li>
  <li>Supports Docker containerized deployment with one-click service startup</li>
  <li>Perfect compatibility with servers and edge computing devices (such as RK3588 and other ARM architecture devices)</li>
  <li>Provides complete automated installation scripts to simplify deployment</li>
</ul>
</div>

<div style="padding: 20px; background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); border-radius: 10px; color: white; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
<h4 style="margin-top: 0; color: white; font-size: 18px;">🍎 Mac Deployment Advantages</h4>
<ul style="font-size: 14px; line-height: 1.8; margin: 10px 0; padding-left: 20px;">
  <li>Suitable for development and testing environments with deep macOS integration</li>
  <li>Supports local development and debugging for rapid feature validation</li>
  <li>Provides convenient installation scripts compatible with package managers like Homebrew</li>
</ul>
</div>

<div style="padding: 20px; background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%); border-radius: 10px; color: white; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
<h4 style="margin-top: 0; color: white; font-size: 18px;">🪟 Windows Deployment Advantages</h4>
<ul style="font-size: 14px; line-height: 1.8; margin: 10px 0; padding-left: 20px;">
  <li>Suitable for Windows server environments, reducing learning curve</li>
  <li>Supports PowerShell automation scripts to simplify deployment operations</li>
  <li>Compatible with both Windows Server and desktop Windows systems</li>
  <li>Provides graphical installation wizards for user-friendly experience</li>
</ul>
</div>

</div>


<p style="font-size: 14px; line-height: 1.8; color: #2c3e50; font-weight: 500; margin: 20px 0; padding: 15px; background-color: #e8f4f8; border-left: 4px solid #3498db; border-radius: 4px;">
<strong>Unified Experience</strong>: Regardless of the operating system chosen, EasyAIoT provides consistent installation scripts and deployment documentation, ensuring a uniform cross-platform deployment experience.
</p>

## ☁️ EasyAIoT = AI + IoT = Cloud-Edge Integrated Solution

<p style="font-size: 15px; line-height: 1.8; color: #333; margin: 15px 0;">
Supports thousands of vertical scenarios with customizable AI models and algorithm development.
</p>

<div style="background-color: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #3498db;">
<h3 style="color: #2c3e50; margin-top: 0;">Deep Integration Empowers Intelligent Vision for Everything</h3>
<p style="font-size: 14px; line-height: 1.8; color: #555; margin: 10px 0;">
EasyAIoT constructs an efficient access and management network for IoT devices (especially massive cameras). We deeply integrate real-time streaming technology with cutting-edge AI to create a unified service core. This solution not only enables interoperability across heterogeneous devices but also deeply integrates HD video streams with powerful AI analytics engines, giving surveillance systems "intelligent eyes" – accurately enabling facial recognition, abnormal behavior analysis, risk personnel monitoring, and perimeter intrusion detection.
</p>
<p style="font-size: 14px; line-height: 1.8; color: #555; margin: 10px 0;">
The platform supports two types of algorithm tasks: real-time algorithm tasks for real-time video analysis of RTSP/RTMP streams, providing millisecond-level response capabilities; snapshot algorithm tasks for intelligent analysis of captured images, supporting event backtracking and image retrieval. Through algorithm task management, flexible frame extraction and sorting strategies are achieved, with each task able to bind independent frame extractors and sorters. Combined with model service cluster inference capabilities, millisecond-level response and high availability are ensured. Additionally, two defense strategies are provided: full defense mode and half defense mode, allowing flexible configuration of monitoring rules for different time periods, achieving precise time-based intelligent monitoring and alerting.
</p>
<p style="font-size: 14px; line-height: 1.8; color: #555; margin: 10px 0;">
In terms of IoT device management, EasyAIoT provides comprehensive device lifecycle management capabilities, supporting multiple IoT protocols (MQTT, TCP, HTTP) to achieve rapid device access, secure authentication, real-time monitoring, and intelligent control. Through the rule engine, intelligent data flow and processing of device data are realized, combined with AI capabilities for in-depth analysis of device data, achieving full-process automation from device access, data collection, intelligent analysis to decision execution, truly realizing interconnected everything and intelligent control of everything.
</p>
</div>

<img src=".image/iframe1.jpg" alt="EasyAIoT Platform Architecture" style="max-width: 100%; height: auto; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.15);">

## ⚠️ Disclaimer

EasyAIoT is an open-source learning project unrelated to commercial activities. Users must comply with laws and
regulations and refrain from illegal activities. If EasyAIoT discovers user violations, it will cooperate with
authorities and report to government agencies. Users bear full legal responsibility for illegal actions and shall
compensate third parties for damages caused by usage. All EasyAIoT-related resources are used at the user's own risk.

## 📚 Deployment Documentation

- [Platform Deployment Documentation](.doc/部署文档/平台部署文档.md)

## 🎮 Demo Environment

- Demo URL: http://36.111.47.113:8888/
- Username: admin
- Password: admin123

## ⚙️ Project Repositories

- Gitee: https://gitee.com/soaring-xiongkulu/easyaiot
- Github: https://github.com/soaring-xiongkulu/easyaiot

## 📸 Screenshots
<div>
  <img src=".image/banner/banner-video1000.gif" alt="Screenshot 1" width="49%" style="margin-right: 10px">
  <img src=".image/banner/banner-video1001.gif" alt="Screenshot 1" width="49%">
</div>
<div>
  <img src=".image/banner/banner1091.jpg" alt="Screenshot 1" width="49%" style="margin-right: 10px">
  <img src=".image/banner/banner1092.jpg" alt="Screenshot 1" width="49%">
</div>
<div>
  <img src=".image/banner/banner1001.png" alt="Screenshot 1" width="49%" style="margin-right: 10px">
  <img src=".image/banner/banner1076.jpg" alt="Screenshot 1" width="49%">
</div>
<div>
  <img src=".image/banner/banner1074.jpg" alt="Screenshot 1" width="49%" style="margin-right: 10px">
  <img src=".image/banner/banner1075.jpg" alt="Screenshot 1" width="49%">
</div>
<div>
  <img src=".image/banner/banner1095.jpg" alt="Screenshot 1" width="49%" style="margin-right: 10px">
  <img src=".image/banner/banner1096.jpg" alt="Screenshot 1" width="49%">
</div>
<div>
  <img src=".image/banner/banner1093.jpg" alt="Screenshot 1" width="49%" style="margin-right: 10px">
  <img src=".image/banner/banner1094.jpg" alt="Screenshot 1" width="49%">
</div>
<div>
  <img src=".image/banner/banner1085.jpg" alt="Screenshot 1" width="49%" style="margin-right: 10px">
  <img src=".image/banner/banner1086.jpg" alt="Screenshot 1" width="49%">
</div>
<div>
  <img src=".image/banner/banner1087.jpg" alt="Screenshot 1" width="49%" style="margin-right: 10px">
  <img src=".image/banner/banner1088.jpg" alt="Screenshot 1" width="49%">
</div>
<div>
  <img src=".image/banner/banner1089.jpg" alt="Screenshot 1" width="49%" style="margin-right: 10px">
  <img src=".image/banner/banner1090.jpg" alt="Screenshot 1" width="49%">
</div>
<div>
  <img src=".image/banner/banner1078.jpg" alt="Screenshot 1" width="49%" style="margin-right: 10px">
  <img src=".image/banner/banner1077.jpg" alt="Screenshot 1" width="49%">
</div>
<div>
  <img src=".image/banner/banner1079.jpg" alt="Screenshot 1" width="49%" style="margin-right: 10px">
  <img src=".image/banner/banner1080.jpg" alt="Screenshot 1" width="49%">
</div>
<div>
  <img src=".image/banner/banner1081.jpg" alt="Screenshot 1" width="49%" style="margin-right: 10px">
  <img src=".image/banner/banner1082.jpg" alt="Screenshot 1" width="49%">
</div>
<div>
  <img src=".image/banner/banner1006.jpg" alt="Screenshot 3" width="49%">
  <img src=".image/banner/banner1009.jpg" alt="Screenshot 1" width="49%" style="margin-right: 10px">
</div>
<div>
  <img src=".image/banner/banner1051.jpg" alt="Screenshot 8" width="49%" style="margin-right: 10px">
  <img src=".image/banner/banner1053.jpg" alt="Screenshot 7" width="49%">
</div>
<div>
  <img src=".image/banner/banner1062.jpg" alt="Screenshot 8" width="49%" style="margin-right: 10px">
  <img src=".image/banner/banner1063.png" alt="Screenshot 7" width="49%">
</div>
<div>
  <img src=".image/banner/banner1064.jpg" alt="Screenshot 8" width="49%" style="margin-right: 10px">
  <img src=".image/banner/banner1065.jpg" alt="Screenshot 7" width="49%">
</div>
<div>
  <img src=".image/banner/banner1066.jpg" alt="Screenshot 8" width="49%" style="margin-right: 10px">
  <img src=".image/banner/banner1067.jpg" alt="Screenshot 7" width="49%">
</div>
<div>
  <img src=".image/banner/banner1052.jpg" alt="Screenshot 7" width="49%" style="margin-right: 10px">
  <img src=".image/banner/banner1054.jpg" alt="Screenshot 7" width="49%">
</div>
<div>
  <img src=".image/banner/banner1083.jpg" alt="Screenshot 7" width="49%" style="margin-right: 10px">
  <img src=".image/banner/banner1084.jpg" alt="Screenshot 7" width="49%">
</div>
<div>
  <img src=".image/banner/banner1055.jpg" alt="Screenshot 7" width="49%" style="margin-right: 10px">
  <img src=".image/banner/banner1056.jpg" alt="Screenshot 7" width="49%">
</div>
<div>
  <img src=".image/banner/banner1057.jpg" alt="Screenshot 7" width="49%" style="margin-right: 10px">
  <img src=".image/banner/banner1058.jpg" alt="Screenshot 7" width="49%">
</div>
<div>
  <img src=".image/banner/banner1068.jpg" alt="Screenshot 7" width="49%" style="margin-right: 10px">
  <img src=".image/banner/banner1069.jpg" alt="Screenshot 7" width="49%">
</div>
<div>
  <img src=".image/banner/banner1026.jpg" alt="Screenshot 8" width="49%" style="margin-right: 10px">
  <img src=".image/banner/banner1028.jpg" alt="Screenshot 7" width="49%">
</div>
<div>
  <img src=".image/banner/banner1029.jpg" alt="Screenshot 8" width="49%" style="margin-right: 10px">
  <img src=".image/banner/banner1030.jpg" alt="Screenshot 7" width="49%">
</div>
<div>
  <img src=".image/banner/banner1072.jpg" alt="Screenshot 7" width="49%" style="margin-right: 10px">
  <img src=".image/banner/banner1031.jpg" alt="Screenshot 8" width="49%">
</div>
<div>
  <img src=".image/banner/banner1070.jpg" alt="Screenshot 8" width="49%" style="margin-right: 10px">
  <img src=".image/banner/banner1071.jpg" alt="Screenshot 8" width="49%">
</div>
<div>
  <img src=".image/banner/banner1033.jpg" alt="Screenshot 8" width="49%" style="margin-right: 10px">
  <img src=".image/banner/banner1035.jpg" alt="Screenshot 7" width="49%">
</div>
<div>
  <img src=".image/banner/banner1034.jpg" alt="Screenshot 8" width="49%" style="margin-right: 10px">
  <img src=".image/banner/banner1036.jpg" alt="Screenshot 7" width="49%">
</div>
<div>
  <img src=".image/banner/banner1037.jpg" alt="Screenshot 8" width="49%" style="margin-right: 10px">
  <img src=".image/banner/banner1038.jpg" alt="Screenshot 7" width="49%">
</div>
<div>
  <img src=".image/banner/banner1015.png" alt="Screenshot 5" width="49%" style="margin-right: 10px">
  <img src=".image/banner/banner1010.jpg" alt="Screenshot 3" width="49%">
</div>
<div>
  <img src=".image/banner/banner1027.png" alt="Screenshot 2" width="49%" style="margin-right: 10px">
  <img src=".image/banner/banner1016.jpg" alt="Screenshot 6" width="49%">
</div>
<div>
  <img src=".image/banner/banner1059.jpg" alt="Screenshot 7" width="49%" style="margin-right: 10px">
  <img src=".image/banner/banner1060.jpg" alt="Screenshot 8" width="49%">
</div>
<div>
  <img src=".image/banner/banner1007.jpg" alt="Screenshot 7" width="49%" style="margin-right: 10px">
  <img src=".image/banner/banner1008.jpg" alt="Screenshot 8" width="49%">
</div>
<div>
  <img src=".image/banner/banner1019.jpg" alt="Screenshot 7" width="49%" style="margin-right: 10px">
  <img src=".image/banner/banner1020.jpg" alt="Screenshot 8" width="49%">
</div>
<div>
  <img src=".image/banner/banner1023.jpg" alt="Screenshot 7" width="49%" style="margin-right: 10px">
  <img src=".image/banner/banner1024.jpg" alt="Screenshot 8" width="49%">
</div>
<div>
  <img src=".image/banner/banner1017.jpg" alt="Screenshot 7" width="49%" style="margin-right: 10px">
  <img src=".image/banner/banner1018.jpg" alt="Screenshot 8" width="49%">
</div>
<div>
  <img src=".image/banner/banner1039.jpg" alt="Screenshot 7" width="49%" style="margin-right: 10px">
  <img src=".image/banner/banner1061.jpg" alt="Screenshot 7" width="49%">
</div>
<div>
  <img src=".image/banner/banner1040.jpg" alt="Screenshot 8" width="49%" style="margin-right: 10px">
  <img src=".image/banner/banner1042.jpg" alt="Screenshot 8" width="49%">
</div>
<div>
  <img src=".image/banner/banner1043.jpg" alt="Screenshot 7" width="49%" style="margin-right: 10px">
  <img src=".image/banner/banner1044.jpg" alt="Screenshot 8" width="49%">
</div>
<div>
  <img src=".image/banner/banner1021.jpg" alt="Screenshot 7" width="49%" style="margin-right: 10px">
  <img src=".image/banner/banner1022.jpg" alt="Screenshot 8" width="49%">
</div>
<div>
  <img src=".image/banner/banner1045.jpg" alt="Screenshot 7" width="49%" style="margin-right: 10px">
  <img src=".image/banner/banner1046.jpg" alt="Screenshot 8" width="49%">
</div>
<div>
  <img src=".image/banner/banner1047.jpg" alt="Screenshot 7" width="49%" style="margin-right: 10px">
  <img src=".image/banner/banner1048.jpg" alt="Screenshot 8" width="49%">
</div>
<div>
  <img src=".image/banner/banner1049.jpg" alt="Screenshot 7" width="49%" style="margin-right: 10px">
  <img src=".image/banner/banner1050.jpg" alt="Screenshot 8" width="49%">
</div>
<div>
  <img src=".image/banner/banner1013.jpg" alt="Screenshot 9" width="49%" style="margin-right: 10px">
  <img src=".image/banner/banner1014.png" alt="Screenshot 10" width="49%">
</div>
<div>
  <img src=".image/banner/banner1003.png" alt="Screenshot 13" width="49%" style="margin-right: 10px">
  <img src=".image/banner/banner1004.png" alt="Screenshot 14" width="49%">
</div>
<div>
  <img src=".image/banner/banner1005.png" alt="Screenshot 15" width="49%" style="margin-right: 10px">
  <img src=".image/banner/banner1002.png" alt="Screenshot 16" width="49%">
</div>

## 📞 Contact Information (After adding WeChat, please follow the official account to join the technical exchange group)

<div>
  <img src=".image/联系方式.jpg" alt="Contact Information" width="30%" style="margin-right: 50px;">
</div>

## 👥 Official Account

<div>
  <img src=".image/公众号.jpg" alt="Official Account" width="30%">
</div>

## 🪐 Knowledge Planet:

<p>
  <img src=".image/知识星球.jpg" alt="知识星球" width="30%">
</p>

## 💰 Sponsorship

<div>
    <img src=".image/微信支付.jpg" alt="WeChat Pay" width="30%" height="30%">
    <img src=".image/支付宝支付.jpg" alt="Alipay" width="30%" height="10%">
</div>

## 🤝 Contributing

<p style="font-size: 15px; line-height: 1.8; color: #333; margin: 15px 0;">
We welcome all forms of contributions! Whether you are a code developer, documentation writer, or issue reporter, your contribution will help make EasyAIoT better. Here are the main ways to contribute:
</p>

<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin: 20px 0;">

<div style="padding: 20px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius: 10px; color: white; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
<h4 style="margin-top: 0; color: white; font-size: 18px;">💻 Code Contribution</h4>
<ul style="font-size: 14px; line-height: 1.8; margin: 10px 0; padding-left: 20px;">
  <li>Fork the project to your GitHub/Gitee account</li>
  <li>Create a feature branch (git checkout -b feature/AmazingFeature)</li>
  <li>Commit your changes (git commit -m 'Add some AmazingFeature')</li>
  <li>Push to the branch (git push origin feature/AmazingFeature)</li>
  <li>Open a Pull Request</li>
</ul>
</div>

<div style="padding: 20px; background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); border-radius: 10px; color: white; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
<h4 style="margin-top: 0; color: white; font-size: 18px;">📚 Documentation Contribution</h4>
<ul style="font-size: 14px; line-height: 1.8; margin: 10px 0; padding-left: 20px;">
  <li>Improve existing documentation content</li>
  <li>Add usage examples and best practices</li>
  <li>Provide multilingual translations</li>
  <li>Fix documentation errors</li>
</ul>
</div>

<div style="padding: 20px; background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%); border-radius: 10px; color: white; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
<h4 style="margin-top: 0; color: white; font-size: 18px;">🌟 Other Ways to Contribute</h4>
<ul style="font-size: 14px; line-height: 1.8; margin: 10px 0; padding-left: 20px;">
  <li>Report and fix bugs</li>
  <li>Suggest feature improvements</li>
  <li>Participate in community discussions and help other developers</li>
  <li>Share usage experiences and case studies</li>
</ul>
</div>

</div>

## 🌟 Major Contributors

<p style="font-size: 15px; line-height: 1.8; color: #333; margin: 15px 0;">
The following are outstanding contributors who have made significant contributions to the EasyAIoT project. Their contributions have played a key role in promoting the project's development. We express our most sincere gratitude!
</p>

<table style="width: 100%; border-collapse: collapse; margin: 20px 0; font-size: 14px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
<thead>
<tr style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white;">
<th style="padding: 15px; text-align: left; font-weight: 600; border: 1px solid #e0e0e0;">Contributor</th>
<th style="padding: 15px; text-align: left; font-weight: 600; border: 1px solid #e0e0e0;">Contribution</th>
</tr>
</thead>
<tbody>
<tr style="background-color: #f8f9fa;">
<td style="padding: 15px; border: 1px solid #e0e0e0; font-weight: 600; color: #2c3e50; width: 20%;">℡夏别</td>
<td style="padding: 15px; border: 1px solid #e0e0e0; color: #444; line-height: 1.8;">Contributed Windows deployment documentation for the EasyAIoT project, providing a complete deployment guide for Windows platform users, greatly reducing the deployment difficulty in Windows environments, and enabling more users to easily use the EasyAIoT platform.</td>
</tr>
<tr>
<td style="padding: 15px; border: 1px solid #e0e0e0; font-weight: 600; color: #2c3e50; width: 20%;">YiYaYiYaho</td>
<td style="padding: 15px; border: 1px solid #e0e0e0; color: #444; line-height: 1.8;">Contributed Mac container one-click deployment script for the EasyAIoT project, providing an automated deployment solution for Mac platform users, significantly simplifying the deployment process in Mac environments, and improving the deployment experience for developers and users.</td>
</tr>
<tr style="background-color: #f8f9fa;">
<td style="padding: 15px; border: 1px solid #e0e0e0; font-weight: 600; color: #2c3e50; width: 20%;">山寒</td>
<td style="padding: 15px; border: 1px solid #e0e0e0; color: #444; line-height: 1.8;">Contributed Linux container deployment script for the EasyAIoT project, providing a containerized deployment solution for Linux platform users, achieving fast and reliable container deployment, and providing important guarantees for stable operation in production environments.</td>
</tr>
<tr>
<td style="padding: 15px; border: 1px solid #e0e0e0; font-weight: 600; color: #2c3e50; width: 20%;">玖零。</td>
<td style="padding: 15px; border: 1px solid #e0e0e0; color: #444; line-height: 1.8;">Contributed Linux container deployment script for the EasyAIoT project, further improving the containerized deployment solution for Linux platforms, providing more options for users of different Linux distributions, and promoting the project's cross-platform deployment capabilities.</td>
</tr>
</tbody>
</table>

<p style="font-size: 14px; line-height: 1.8; color: #2c3e50; font-weight: 500; margin: 20px 0; padding: 15px; background-color: #e8f4f8; border-left: 4px solid #3498db; border-radius: 4px;">
<strong>Special Thanks</strong>: The work of the above contributors has laid a solid foundation for EasyAIoT's cross-platform deployment capabilities. Their professionalism and selfless dedication are worthy of our learning and respect. Once again, we express our most sincere gratitude to these outstanding contributors! 🙏
</p>

## 🙏 Acknowledgements

Thanks to the following contributors for code, feedback, donations, and support (in no particular order):
<table>
  <tbody>
    <tr>
      <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src=".image/sponsor/icon.jpg" width="80px;" alt="icon"/><br /><sub><b>icon</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/jiang4yu" target="_blank"><img src=".image/sponsor/山寒.jpg" width="80px;" alt="山寒"/><br /><sub><b>山寒</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/baobaomo" target="_blank"><img src="./.image/sponsor/放学丶别走.jpg" width="80px;" alt="放学丶别走"/><br /><sub><b>放学丶别走</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/wagger" target="_blank"><img src="./.image/sponsor/春和.jpg" width="80px;" alt="春和"/><br /><sub><b>春和</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/longbinwu" target="_blank"><img src="./.image/sponsor/章鱼小丸子.jpg" width="80px;" alt="章鱼小丸子"/><br /><sub><b>章鱼小丸子</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/Catwings.jpg" width="80px;" alt="Catwings"/><br /><sub><b>Catwings</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/小工头.jpg" width="80px;" alt="小工头"/><br /><sub><b>小工头</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/西乡一粒沙.jpg" width="80px;" alt="西乡一粒沙"/><br /><sub><b>西乡一粒沙</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/L_Z_M" target="_blank"><img src=".image/sponsor/玖零。.jpg" width="80px;" alt="玖零。"/><br /><sub><b>玖零。</b></sub></a></td>
    </tr>
    <tr>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/36436022" target="_blank"><img src=".image/sponsor/金鸿伟.jpg" width="80px;" alt="金鸿伟"/><br /><sub><b>金鸿伟</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/cnlijf" target="_blank"><img src="./.image/sponsor/李江峰.jpg" width="80px;" alt="李江峰"/><br /><sub><b>李江峰</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src=".image/sponsor/Best%20Yao.jpg" width="80px;" alt="Best Yao"/><br /><sub><b>Best Yao</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/weiloser" target="_blank"><img src=".image/sponsor/无为而治.jpg" width="80px;" alt="无为而治"/><br /><sub><b>无为而治</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/shup092_admin" target="_blank"><img src="./.image/sponsor/shup.jpg" width="80px;" alt="shup"/><br /><sub><b>shup</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/gampa" target="_blank"><img src="./.image/sponsor/也许.jpg" width="80px;" alt="也许"/><br /><sub><b>也许</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/leishaozhuanshudi" target="_blank"><img src="./.image/sponsor/⁰ʚᦔrꫀꪖꪑ⁰ɞ%20..jpg" width="80px;" alt="⁰ʚᦔrꫀꪖꪑ⁰ɞ ."/><br /><sub><b>⁰ʚᦔrꫀꪖꪑ⁰ɞ .</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/fateson" target="_blank"><img src="./.image/sponsor/逆.jpg" width="80px;" alt="逆"/><br /><sub><b>逆</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/dongGezzz_admin" target="_blank"><img src="./.image/sponsor/廖东旺.jpg" width="80px;" alt="廖东旺"/><br /><sub><b>廖东旺</b></sub></a></td>
    </tr>
    <tr>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/huangzhen1993" target="_blank"><img src="./.image/sponsor/黄振.jpg" width="80px;" alt="黄振"/><br /><sub><b>黄振</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://github.com/fengchunshen" target="_blank"><img src="./.image/sponsor/春生.jpg" width="80px;" alt="春生"/><br /><sub><b>春生</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/mrfox_wang" target="_blank"><img src="./.image/sponsor/贵阳王老板.jpg" width="80px;" alt="贵阳王老板"/><br /><sub><b>贵阳王老板</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/haobaby" target="_blank"><img src="./.image/sponsor/hao_chen.jpg" width="80px;" alt="hao_chen"/><br /><sub><b>hao_chen</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/finalice" target="_blank"><img src="./.image/sponsor/尽千.jpg" width="80px;" alt="尽千"/><br /><sub><b>尽千</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/yuer629" target="_blank"><img src="./.image/sponsor/yuer629.jpg" width="80px;" alt="yuer629"/><br /><sub><b>yuer629</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/cai-peikai/ai-project" target="_blank"><img src="./.image/sponsor/kong.jpg" width="80px;" alt="kong"/><br /><sub><b>kong</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/HB1731276584" target="_blank"><img src="./.image/sponsor/岁月静好.jpg" width="80px;" alt="岁月静好"/><br /><sub><b>岁月静好</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/hy5128" target="_blank"><img src="./.image/sponsor/Kunkka.jpg" width="80px;" alt="Kunkka"/><br /><sub><b>Kunkka</b></sub></a></td>
    </tr>
    <tr>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/guo-dida" target="_blank"><img src="./.image/sponsor/灬.jpg" width="80px;" alt="灬"/><br /><sub><b>灬</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://github.com/XyhBill" target="_blank"><img src="./.image/sponsor/Mr.LuCkY.jpg" width="80px;" alt="Mr.LuCkY"/><br /><sub><b>Mr.LuCkY</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/timeforeverz" target="_blank"><img src="./.image/sponsor/泓.jpg" width="80px;" alt="泓"/><br /><sub><b>泓</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/mySia" target="_blank"><img src="./.image/sponsor/i.jpg" width="80px;" alt="i"/><br /><sub><b>i</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/依依.jpg" width="80px;" alt="依依"/><br /><sub><b>依依</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/sunbirder" target="_blank"><img src="./.image/sponsor/小菜鸟先飞.jpg" width="80px;" alt="小菜鸟先飞"/><br /><sub><b>小菜鸟先飞</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/mmy0" target="_blank"><img src="./.image/sponsor/追溯未来-_-.jpg" width="80px;" alt="追溯未来"/><br /><sub><b>追溯未来</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/ccqingshan" target="_blank"><img src="./.image/sponsor/青衫.jpg" width="80px;" alt="青衫"/><br /><sub><b>青衫</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/jiangchunJava" target="_blank"><img src="./.image/sponsor/Fae.jpg" width="80px;" alt="Fae"/><br /><sub><b>Fae</b></sub></a></td>
    </tr>
    <tr>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/huang-xiangtai" target="_blank"><img src="./.image/sponsor/憨憨.jpg" width="80px;" alt="憨憨"/><br /><sub><b>憨憨</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/gu-beichen-starlight" target="_blank"><img src="./.image/sponsor/文艺小青年.jpg" width="80px;" alt="文艺小青年"/><br /><sub><b>文艺小青年</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://github.com/zhangnanchao" target="_blank"><img src="./.image/sponsor/lion.jpg" width="80px;" alt="lion"/><br /><sub><b>lion</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/yupccc" target="_blank"><img src="./.image/sponsor/汪汪队立大功.jpg" width="80px;" alt="汪汪队立大功"/><br /><sub><b>汪汪队立大功</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/wcjjjjjjj" target="_blank"><img src="./.image/sponsor/wcj.jpg" width="80px;" alt="wcj"/><br /><sub><b>wcj</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/hufanglei" target="_blank"><img src="./.image/sponsor/🌹怒放de生命😋.jpg" width="80px;" alt="怒放de生命"/><br /><sub><b>怒放de生命</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/juyunsuan" target="_blank"><img src="./.image/sponsor/蓝速传媒.jpg" width="80px;" alt="蓝速传媒"/><br /><sub><b>蓝速传媒</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/achieve275" target="_blank"><img src="./.image/sponsor/Achieve_Xu.jpg" width="80px;" alt="Achieve_Xu"/><br /><sub><b>Achieve_Xu</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/nicholasld" target="_blank"><img src="./.image/sponsor/NicholasLD.jpg" width="80px;" alt="NicholasLD"/><br /><sub><b>NicholasLD</b></sub></a></td>
    </tr>
    <tr>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/ADVISORYZ" target="_blank"><img src=".image/sponsor/ADVISORYZ.jpg" width="80px;" alt="ADVISORYZ"/><br /><sub><b>ADVISORYZ</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/dongxinji" target="_blank"><img src="./.image/sponsor/take%20your%20time%20or.jpg" width="80px;" alt="take your time or"/><br /><sub><b>take your time or</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://github.com/xu756" target="_blank"><img src="./.image/sponsor/碎碎念..jpg" width="80px;" alt="碎碎念."/><br /><sub><b>碎碎念.</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/lwisme" target="_blank"><img src="./.image/sponsor/北街.jpg" width="80px;" alt="北街"/><br /><sub><b>北街</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/yu-xinyan71" target="_blank"><img src="./.image/sponsor/Dorky%20TAT.jpg" width="80px;" alt="Dorky TAT"/><br /><sub><b>Dorky TAT</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/chenxiaohong" target="_blank"><img src=".image/sponsor/右耳向西.jpg" width="80px;" alt="右耳向西"/><br /><sub><b>右耳向西</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://github.com/派大星" target="_blank"><img src="./.image/sponsor/派大星.jpg" width="80px;" alt="派大星"/><br /><sub><b>派大星</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/wz_vue_gitee_181" target="_blank"><img src="./.image/sponsor/棒槌🧿🍹🍹🧿.jpg" width="80px;" alt="棒槌🧿🍹🍹🧿"/><br /><sub><b>棒槌</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/nctwo" target="_blank"><img src=".image/sponsor/信微输传助手.jpg" width="80px;" alt="信微输传助手"/><br /><sub><b>信微输传助手</b></sub></a></td>
    </tr>
    <tr>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/l9999_admin" target="_blank"><img src=".image/sponsor/一往无前.jpg" width="80px;" alt="一往无前"/><br /><sub><benen>一往无前</benen></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/stenin" target="_blank"><img src="./.image/sponsor/Charon.jpg" width="80px;" alt="Charon"/><br /><sub><b>Charon</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/zhao-yihuiwifi" target="_blank"><img src="./.image/sponsor/赵WIFI..jpg" width="80px;" alt="赵WIFI."/><br /><sub><b>赵WIFI.</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/Yang619" target="_blank"><img src="./.image/sponsor/Chao..jpg" width="80px;" alt="Chao."/><br /><sub><b>Chao.</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/lcrsd123" target="_blank"><img src=".image/sponsor/城市稻草人.jpg" width="80px;" alt="城市稻草人"/><br /><sub><b>城市稻草人</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/Mo_bai1016" target="_blank"><img src=".image/sponsor/Bug写手墨白.jpg" width="80px;" alt="Bug写手墨白"/><br /><sub><b>Bug写手墨白</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/kevinosc_admin" target="_blank"><img src=".image/sponsor/kevin.jpg" width="80px;" alt="kevin"/><br /><sub><b>kevin</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/lhyicn" target="_blank"><img src=".image/sponsor/童年.jpg" width="80px;" alt="童年"/><br /><sub><b>童年</b></sub></a></td>
      <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/dubai100" target="_blank"><img src="./.image/sponsor/sherry金.jpg" width="80px;" alt="sherry金"/><br /><sub><b>sherry金</b></sub></a></td>
    </tr>
    <tr>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/℡夏别.jpg" width="80px;" alt="℡夏别"/><br /><sub><b>℡夏别</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/翠翠草原.jpg" width="80px;" alt="翠翠草原"/><br /><sub><b>翠翠草原</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/慕容曦.jpg" width="80px;" alt="慕容曦"/><br /><sub><b>慕容曦</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/Tyrion.jpg" width="80px;" alt="Tyrion"/><br /><sub><b>Tyrion</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/大漠孤烟.jpg" width="80px;" alt="大漠孤烟"/><br /><sub><b>大漠孤烟</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/Return.jpg" width="80px;" alt="Return"/><br /><sub><b>Return</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/一杯拿铁.jpg" width="80px;" alt="一杯拿铁"/><br /><sub><b>一杯拿铁</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/Thuri.jpg" width="80px;" alt="Thuri"/><br /><sub><b>Thuri</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/Liu.jpg" width="80px;" alt="Liu"/><br /><sub><b>Liu</b></sub></a></td>
    </tr>
    <tr>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/三金.jpg" width="80px;" alt="三金"/><br /><sub><b>三金</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/ZPort.jpg" width="80px;" alt="ZPort"/><br /><sub><b>ZPort</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/Li.jpg" width="80px;" alt="Li"/><br /><sub><b>Li</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/嘉树.jpg" width="80px;" alt="嘉树"/><br /><sub><b>嘉树</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/俊采星驰.jpg" width="80px;" alt="俊采星驰"/><br /><sub><b>俊采星驰</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/oi.jpg" width="80px;" alt="oi"/><br /><sub><b>oi</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/ZhangY_000.jpg" width="80px;" alt="ZhangY_000"/><br /><sub><b>ZhangY_000</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/℡夏别.jpg" width="80px;" alt="℡夏别"/><br /><sub><b>℡夏别</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/张瑞麟.jpg" width="80px;" alt="张瑞麟"/><br /><sub><b>张瑞麟</b></sub></a></td>
    </tr>
    <tr>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/Lion King.jpg" width="80px;" alt="Lion King"/><br /><sub><b>Lion King</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/Frank.jpg" width="80px;" alt="Frank"/><br /><sub><b>Frank</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/徐梦阳.jpg" width="80px;" alt="徐梦阳"/><br /><sub><b>徐梦阳</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/九月.jpg" width="80px;" alt="九月"/><br /><sub><b>九月</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/tangl伟.jpg" width="80px;" alt="tangl伟"/><br /><sub><b>tangl伟</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/冯瑞伦.jpg" width="80px;" alt="冯瑞伦"/><br /><sub><b>冯瑞伦</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/杨林.jpg" width="80px;" alt="杨林"/><br /><sub><b>杨林</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/梧桐有语。.jpg" width="80px;" alt="梧桐有语。"/><br /><sub><b>梧桐有语。</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/歌德de花烛.jpg" width="80px;" alt="歌德de花烛"/><br /><sub><b>歌德de花烛</b></sub></a></td>
    </tr>
    <tr>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/泥嚎.jpg" width="80px;" alt="泥嚎"/><br /><sub><b>泥嚎</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/翠翠草原.jpg" width="80px;" alt="翠翠草原"/><br /><sub><b>翠翠草原</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/胡泽龙.jpg" width="80px;" alt="胡泽龙"/><br /><sub><b>胡泽龙</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/苏叶.jpg" width="80px;" alt="苏叶"/><br /><sub><b>苏叶</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/裴先生.jpg" width="80px;" alt="裴先生"/><br /><sub><b>裴先生</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/谭远彪.jpg" width="80px;" alt="谭远彪"/><br /><sub><b>谭远彪</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/陈祺.jpg" width="80px;" alt="陈祺"/><br /><sub><b>陈祺</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/零点就睡.jpg" width="80px;" alt="零点就睡"/><br /><sub><b>零点就睡</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/风之羽.jpg" width="80px;" alt="风之羽"/><br /><sub><b>风之羽</b></sub></a></td>
    </tr>
    <tr>
        <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/fufeng1908" target="_blank"><img src="./.image/sponsor/王守仁.jpg" width="80px;" alt="王守仁"/><br /><sub><b>王守仁</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/kaigejava" target="_blank"><img src="./.image/sponsor/狼ྂ图ྂ腾ྂ.jpg" width="80px;" alt="狼图腾"/><br /><sub><b>狼图腾</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/马到成功.jpg" width="80px;" alt="马到成功"/><br /><sub><b>马到成功</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/做生活的高手.jpg" width="80px;" alt="做生活的高手"/><br /><sub><b>做生活的高手</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/清欢之恋.jpg" width="80px;" alt="清欢之恋"/><br /><sub><b>清欢之恋</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/绝域时空.jpg" width="80px;" alt="绝域时空"/><br /><sub><b>绝域时空</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/风雨.jpg" width="80px;" alt="风雨"/><br /><sub><b>风雨</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/Nicola.jpg" width="80px;" alt="Nicola"/><br /><sub><b>Nicola</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/云住.jpg" width="80px;" alt="云住"/><br /><sub><b>云住</b></sub></a></td>
    </tr>
    <tr>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/Mr.Zhang.jpg" width="80px;" alt="Mr.Zhang"/><br /><sub><b>Mr.Zhang</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/剑.jpg" width="80px;" alt="剑"/><br /><sub><b>剑</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/shen.jpg" width="80px;" alt="shen"/><br /><sub><b>shen</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/嗯.jpg" width="80px;" alt="嗯"/><br /><sub><b>嗯</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/周华.jpg" width="80px;" alt="周华"/><br /><sub><b>周华</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/太阳鸟.jpg" width="80px;" alt="太阳鸟"/><br /><sub><b>太阳鸟</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/了了.jpg" width="80px;" alt="了了"/><br /><sub><b>了了</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/第七次日落.jpg" width="80px;" alt="第七次日落"/><br /><sub><b>第七次日落</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/npc.jpg" width="80px;" alt="npc"/><br /><sub><b>npc</b></sub></a></td>
    </tr>
    <tr>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/承担不一样的天空.jpg" width="80px;" alt="承担不一样的天空"/><br /><sub><b>承担不一样的天空</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/铁木.jpg" width="80px;" alt="铁木"/><br /><sub><b>铁木</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/Orion.jpg" width="80px;" alt="Orion"/><br /><sub><b>Orion</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/森源-金福洪.jpg" width="80px;" alt="森源-金福洪"/><br /><sub><b>森源-金福洪</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/薛继超.jpg" width="80px;" alt="薛继超"/><br /><sub><b>薛继超</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/虎虎虎.jpg" width="80px;" alt="虎虎虎"/><br /><sub><b>虎虎虎</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/Everyman.jpg" width="80px;" alt="Everyman"/><br /><sub><b>Everyman</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/NXL.jpg" width="80px;" alt="NXL"/><br /><sub><b>NXL</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/孙涛.jpg" width="80px;" alt="孙涛"/><br /><sub><b>孙涛</b></sub></a></td>
    </tr>
    <tr>
        <td align="center" valign="top" width="11.11%"><a href="https://gitee.com/bcake" target="_blank"><img src=".image/sponsor/大饼.jpg" width="80px;" alt="大饼"/><br /><sub><b>大饼</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/hrsjw1.jpg" width="80px;" alt="hrsjw1"/><br /><sub><b>hrsjw1</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/linguanghuan.jpg" width="80px;" alt="linguanghuan"/><br /><sub><b>linguanghuan</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/YiYaYiYaho.jpg" width="80px;" alt="YiYaYiYaho"/><br /><sub><b>YiYaYiYaho</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/慢慢慢.jpg" width="80px;" alt="慢慢慢"/><br /><sub><b>慢慢慢</b></sub></a></td>
        <td align="center" valign="top" width="11.11%"><a href="javascript:void(0)" target="_blank"><img src="./.image/sponsor/lilOne.jpg" width="80px;" alt="lilOne"/><br /><sub><b>lilOne</b></sub></a></td>
    </tr>
  </tbody>
</table>

## 💡 Expectations

<p style="font-size: 15px; line-height: 1.8; color: #333; margin: 15px 0;">
We welcome suggestions for improvement to help refine easyaiot.
</p>

## 📄 Copyright

<p style="font-size: 15px; line-height: 1.8; color: #333; margin: 15px 0;">
Soaring Xiongkulu / easyaiot is licensed under the <a href="https://gitee.com/soaring-xiongkulu/easyaiot/blob/main/LICENSE" style="color: #3498db; text-decoration: none; font-weight: 600;">MIT LICENSE</a>. We are committed to promoting the popularization and development of AI technology, enabling more people to freely use and benefit from this technology.
</p>

<p style="font-size: 15px; line-height: 1.8; color: #333; margin: 15px 0;">
<strong>Usage License</strong>: Individuals and enterprises can use it 100% free of charge, without the need to retain author or Copyright information. We believe the value of technology lies in its widespread use and continuous innovation, not in being bound by copyright. We hope you can freely use, modify, and distribute this project, making AI technology truly benefit everyone.
</p>

## 🌟 Star Growth Trend Chart

[![Stargazers over time](https://starchart.cc/soaring-xiongkulu/easyaiot.svg?variant=adaptive)](https://starchart.cc/soaring-xiongkulu/easyaiot)