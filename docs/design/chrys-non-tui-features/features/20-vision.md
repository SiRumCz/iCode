# 20 · Vision / 多模态图片

## Chrys 摘要

用户消息可带图片；校验与压缩后写入 `UserMessage.prepared_contents`；依赖视觉模型能力。

- 路径：kernel `images.py`、service `vision.py`、事件字段 `prepared_contents`

## agent-core 现状

**复用。** `harness/tools/multimodal/vision.py`、image probe、CLI 条件启用。

## 迁移方案

1. 继续用现有 multimodal 路径。
2. EventBus：`UserMessage` 可带附件引用；Host 在进模型前做校验/压缩，失败发 `Error`/`Warning`。
3. ACP/编辑器路径再接 resource/image prompt（跟 13 联动）。

**落点：** 现有 multimodal；Host 做附件 ingress。
