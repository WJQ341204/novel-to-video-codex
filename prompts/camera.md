# 运镜词典

给图生视频用的**镜头运动**片段。格式 `- key: 英文提示词片段 —— 中文说明`。
用法：`promptbank.get("camera", "push_in")`，或拼进 `scene["vid"]`。

选型原则：竖屏漫剧以**慢速、小幅**为主，大幅运镜在 Wan2.2-5B 上容易糊；
一个镜头只写一种运动，别叠加。

## 推拉

- push_in: slow push in toward the subject, languid pace, cinematic —— 慢推，最常用，聚焦情绪
- push_in_fast: rapid push in, accelerating, urgent —— 快推，用于惊觉/爆发
- pull_out: slow pull back revealing the surroundings, cinematic —— 慢拉，交代环境
- pull_out_reveal: pull back to reveal the full scene, dramatic reveal —— 拉出揭示，用于反转
- dolly_zoom: dolly zoom effect, background compressing while subject stays same size —— 推焦，眩晕/震惊

## 摇移

- pan_left: slow camera pan to the left, smooth —— 左摇，扫环境
- pan_right: slow camera pan to the right, smooth —— 右摇
- truck_left: subtle camera drift to the left, slow motion —— 左移（比摇更柔）
- truck_right: subtle camera drift to the right, slow motion —— 右移
- tilt_up: slow tilt up from the ground to the subject's face —— 上摇，压迫感/登场
- tilt_down: slow tilt down from the sky to the subject —— 下摇

## 跟随与环绕

- follow: camera follows the subject from behind, steady —— 跟拍
- orbit: slow camera orbit around the subject, 30 degrees —— 环绕，展示人物/物件
- orbit_half: slow half circle orbit around the subject —— 半环绕，转场感
- crane_up: slow crane up rising above the scene —— 升起，收尾/宏大
- crane_down: slow crane down into the scene —— 下降，入场

## 静态与手持

- static: locked-off static shot, only the subject moves —— 固定机位，最稳，适合对话
- handheld: subtle handheld camera shake, documentary feel —— 手持微晃，真实感
- handheld_tense: tense handheld shake, slight instability —— 手持紧张晃，对峙/追逐

## 角度

- low_angle: low angle shot looking up, subject looming —— 仰拍，压迫/强者
- high_angle: high angle shot looking down, subject small —— 俯拍，弱势/孤立
- over_shoulder: over the shoulder shot, two characters in frame —— 过肩，对话
- pov: point of view shot, first person perspective —— 主观视角，代入
- close_up: extreme close-up on the eyes, shallow depth —— 特写眼睛，情绪爆点
- insert: close insert shot on the hands, detail —— 手部特写，细节/动作

## 常用组合

- push_in_then_hold: slow push in then hold still, cinematic —— 推近后停住，最安全的选择
- drift_and_settle: subtle camera drift then settling, slow motion —— 微移后稳定
- lightning_push: sudden quick push in on the flash, snapping into sharp focus —— 闪电一亮瞬间急推（雷夜专用）
