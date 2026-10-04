# 负面提示词分档

分档组合，别一股脑全塞——负面词过多会压制画面质量。
用法：`promptbank.get("neg", "base")`。

## 用法建议

- 通用基线 `base`：所有场景都带
- 按内容叠加：有人物加 `face`，古装加 `costume`，室内加 `interior`
- 单条负面词总长控制在 30~40 个词以内

## 词条

- base: deformed, mutated, ugly, disfigured, blurry, low quality, jpeg artifacts, extra limbs, bad anatomy, missing fingers, watermark, text, logo, signature, oversaturated, cartoon, 3d render, plastic
- face: asymmetric eyes, crossed eyes, mismatched pupils, melted face, duplicate face, warped facial features, uncanny skin, waxy skin, blurry eyes
- hands: extra fingers, fused fingers, missing fingers, deformed hands, two left hands, stumps
- costume: zipper, velcro, modern clothing, wristwatch, sneakers, synthetic fabric, printed pattern, modern jewelry
- interior: modern furniture, ceiling lamp, power outlet, glass window frame, tile floor, plastic chair
- period: car, telephone, antenna, power line, concrete, neon sign, camera crew, modern crowd
- motion: morphing, warping, flickering, jittering, frame blending, ghosting, temporal noise
- text_free: text, letters, characters, subtitles, captions, signature, watermark, numbers
- combo_ancient: deformed, mutated, blurry, low quality, jpeg artifacts, bad anatomy, extra fingers, watermark, text, logo, zipper, modern clothing, wristwatch, neon, concrete, plastic, oversaturated
- combo_closeup: deformed, blurry, low quality, asymmetric eyes, waxy skin, uncanny valley, jpeg artifacts, bad anatomy, extra limbs, watermark
