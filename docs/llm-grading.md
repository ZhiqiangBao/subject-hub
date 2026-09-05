# 大模型评分（只评主观题）

**大模型只判断主观题。** `single` / `multiple` / `blank` / `numeric` 全部在主机用规则比对，请求路径上不经过模型。计算题的**终值**同样只走本地规则。

主观题（`short` / `essay`、材料题里的简答框、过程题的步骤框）不跑测例。主机拿题面、参考答案、评分细则、学生作答（可带演算纸图片）调用配置好的 HTTP 接口，收回分数和评语。

## 通用接口

评测主机上只保留一层很薄的客户端：给定根地址、密钥、模型名，发一段对话，拿回文本。不写死厂商。

配置写在 `data/llm.env`（不进 Git）。环境变量优先；没有再读文件。管理员登录后也可在网页「模型」页填写，默认本机 `http://127.0.0.1:8080/v1`。

```text
SUBJECT_HUB_LLM_BASE_URL     # 服务根地址，例如 https://host.example/v1
SUBJECT_HUB_LLM_API_KEY      # 可选；内网无鉴权的服务可留空
SUBJECT_HUB_LLM_MODEL        # 模型名，原样传给对端
SUBJECT_HUB_LLM_CHAT_PATH    # 可选；默认 /chat/completions
SUBJECT_HUB_LLM_ENABLE_THINKING    # 0 关掉思考（默认）；1 打开
SUBJECT_HUB_LLM_REASONING_EFFORT   # none / low / medium / high；关掉时固定 none
```

思考默认关掉，加快主观题评分。请求按兼容顺序带这些字段（对端不认就自动去掉再试）：

- OpenAI Chat Completions 标准：`reasoning_effort`。关掉用 `none`，调低用 `low`。GPT-5 早期只有 `minimal`，o 系列没有 `none` 时用 `low`。
- 阿里百炼 / 通义 Qwen3+：HTTP JSON 顶层 `enable_thinking: false`（Python SDK 才进 `extra_body`）。
- 本机 vLLM / llama.cpp：`chat_template_kwargs.enable_thinking`。

请求约定：

- 方法 `POST`，JSON 正文。
- 带 `messages`（角色 + 内容）和 `model`。
- 鉴权用 `Authorization: Bearer <key>`（无密钥则不加这头）。
- 从返回 JSON 里取助手文本（常见字段 `choices[0].message.content`）。
- 有演算纸时，用户消息用多模态内容列表（文字 + `image_url`）。对端不能看图则只送文字，并记下「图片未评」。

原则：

- 答题端没有「填 API Key」的页面。密钥只在 Ubuntu。
- 未配置入口时：主观题保持待评分，家长手打；客观题不受影响。
- 超时、限流、非 JSON、校验失败都算这次评分失败，可重评，不覆盖家长已改的分。

## 评分细则

细则写在主观题文件里。客观题没有 `rubric`。

```yaml
type: short
points: 8
reference: |
  指出作者用对比突出主旨，并引用一处原文。
rubric:
  - id: point
    points: 4
    require: 准确概括主旨或对比手法
  - id: evidence
    points: 3
    require: 有具体引文或可定位的段落，不能只空喊
  - id: language
    points: 1
    require: 语句通顺；错别字过多则本项 0
```

过程题的细则按步骤要点给分，不要把终值交给模型。

## 送进模型的内容

每次只评**一个框**：

1. 科目与题型（仅主观）
2. 题面（材料题附上阅读材料；过程题附上题干）
3. 参考答案
4. 细则列表
5. 该框学生作答全文
6. 若有演算纸：图片

不要附带同题终值以外的其它客观答案。不要附带其他学生的作答。

要求模型返回可解析结构：

```json
{
  "items": [
    { "id": "point", "score": 3, "reason": "主旨对，未点出对比" }
  ],
  "total": 3,
  "comment": "……"
}
```

`total` 必须等于分项之和，且每项不超过该条满分。主机再做一次算术校验，对不上则评分失败并转人工。

禁止把系统提示里的密钥说明写进学生可见评语。

## 和家长改判的关系

自动分是初评，写在机评分字段。管理员手改写在另一套字段，作为最终分。

「用模型再评一次」只更新机评分和模型评语，当作参考，**不得覆盖**管理员已经手改的分数。

## 科目上怎么用

| 科目 | 走模型 | 不走模型 |
| --- | --- | --- |
| 语文 | 阅读短答、作文 | 默写、选择 |
| 英语 | 作文、翻译 | 单词填空、选择 |
| 数学 | 过程、证明（可带演算纸） | 计算终值、填空、选择 |
| 物理化学生物 | 过程、实验简述（可带演算纸） | 选择、数值、化学式填空 |
| 历史政治 | 材料简答、辨析 | 选择、填空 |

## 第一期范围

必须有：通用 HTTP 入口、细则只存在主观框上、结构化输出校验、失败可重评、家长改判、演算纸走多模态。

后置：多模型对比、听力口语。
