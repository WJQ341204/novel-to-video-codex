# 电影风格词典

全片基调与影调。**优先用 `assets/cast.json` 的 `styles` 段**（那是项目级、可切换的），
本文件是**素材池**——需要临时变体时从这里挑，挑中后固化回 cast.json。

用法：`promptbank.get("style", "ink_wash")`。

## 影调

- ink_wash: traditional Chinese ink wash mood, rice paper texture, muted monochrome with a single accent color —— 水墨
- chiaroscuro: strong chiaroscuro, single hard light source, deep black shadows —— 明暗对照
- low_key: low-key lighting, mostly shadow, sparse highlights —— 低调光
- high_key: high-key soft lighting, bright and airy —— 高调光
- noir: film noir, venetian blind shadows, high contrast black and white —— 黑色电影
- golden_hour: warm golden hour light, long soft shadows —— 黄金时刻
- rainy_night: rain-soaked night, cold blue ambient with warm window light, wet reflective ground —— 雨夜（青囊主场）

## 质感

- film_grain: 35mm film grain, subtle halation, organic texture —— 胶片颗粒
- anamorphic: anamorphic lens flare, oval bokeh, horizontal streaks —— 变形宽银幕
- soft_focus: soft focus, dreamy haze, blooming highlights —— 柔焦梦幻
- crisp_digital: clean digital sharpness, clinical detail —— 数码锐利

## 构图

- negative_space: minimalist composition with generous negative space —— 留白
- rule_of_thirds: rule of thirds composition, subject off-center —— 三分法
- centered_symmetry: centered symmetrical composition, imposing —— 对称中心
- dutch_angle: slight dutch angle, uneasy tilt —— 荷兰角，不安
- layered_depth: three-layer depth, foreground framing element —— 三层景深

## 氛围

- tense: tense atmosphere, stillness before the storm —— 紧绷
- serene: serene and quiet, unhurried —— 宁和
- eerie: eerie, unsettling, something is wrong —— 诡异
- tragic: tragic weight, inevitable sorrow —— 悲怆
- wuxia: wuxia atmosphere, dust and wind, restrained heroism —— 武侠
