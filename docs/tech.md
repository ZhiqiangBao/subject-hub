# 学科 Hub · 技术架构（代码地图）

本文对照**当前源码**：函数在哪、干什么、改哪一类需求该动哪些文件。产品口径（题型、填空括号、角色）见 [architecture.md](architecture.md)。装机见 [host.md](host.md)。主观题模型协议见 [llm-grading.md](llm-grading.md)。

**改代码时必须同步改本文。** 漏改比没文档更糟。Cursor 规则：`.cursor/rules/tech-doc.mdc`。

---

## 1. 进程与目录

| 路径 | 作用 |
| --- | --- |
| `backend/app/main.py` | FastAPI 入口。`lifespan` 建表、`migrate()`、读题库、回填旧试卷快照并启动持久评分 worker；另绑 `ADMIN_HOST`/`ADMIN_PORT`（默认 `127.0.0.1:8091`）只给本机注册管理员。8090 提供学生站 + 同一套 API。静态页来自 `frontend/dist`。未知 `/api/` 返回 JSON 404「找不到这个接口，重启答题服务后再试」（常见原因：改了路由但 **uvicorn 没重启**）。uvicorn **不热重载**。 |
| `backend/app/config.py` | 路径、端口、LLM 配置（同名环境变量优先，否则读 `data/llm.env`）；出题和判题共用 `llm_settings()`。若环境变量设置模型地址或模型名，网页不能覆盖。 |
| `backend/app/db.py` | SQLite：`data/subject-hub.db`。`migrate()` 给旧库加列/建表，包括 `papers.items_snapshot_json`、`users.created_by`、`student_groups`（`kind`/`parent_id`）、`student_group_members`、`paper_audiences`。旧 `users.group_id` 启动时拷进 members，之后不要再写。 |
| `backend/app/models.py` | ORM 表。 |
| `backend/app/schemas.py` | 请求体。 |
| `backend/app/deps.py` | 登录会话、管理员校验、密码哈希。 |
| `backend/app/constants.py` | 科目、题型、客观题集合、组卷大题规格。 |
| `backend/app/api/` | HTTP 路由。 |
| `backend/app/services/` | 业务，路由尽量只调这里。 |
| `bank/` | 随仓库走的题。 |
| `docs/standards/` | AI 出题用的课标 Markdown、索引、页级转换清单和目视校正记录；PDF 留本地，MD 随 Git 发布。转换与核验入口见该目录 README。 |
| `data/` | 不进 Git：库、本机题 `local-bank/`、上传图、LLM 配置。 |
| `frontend/src/` | Vue 3。改完要 `npm run build`，uvicorn 才吃到 `dist`。 |

时间：**默认北京时间**，顶栏一个下拉可改（东京、新加坡、伦敦、纽约、洛杉矶、UTC、本机）。库里仍存 UTC。填写 `datetime-local` 按所选时区解读（`frontend/src/timeZone.ts`），接口 `timing.utc_iso()` 带 `Z`。开考判断用 `datetime.utcnow()` 和存库 UTC 比，与谁选哪个时区无关。

---

## 2. 表（`models.py`）

| 表 / 类 | 关键字段 | 含义 |
| --- | --- | --- |
| `User` | `role`=`student`/`admin`/`parent`；`subjects_json`；`display_name`；`grade`；`created_by` | 8090 注册永远是学生。8091 才能注册管理员。`*` 或空 = 全科。自注册 `created_by` 空。`username` 是登录名，注册后**不能改**（老师也不能改）；学生端只显示登录名。`display_name` 是老师看的真名，默认等于登录名，只有老师能改；学生接口不返回真名。 |
| | `group_id` | **旧列，不要读写。** 分组成员看 `student_group_members`。 |
| `StudentGroup` | `kind`=`class`/`group`；`name`；`grade`；`parent_id` | **班级是一种分组。** `class`：年级+班名（如 1班）。`group`：可 `parent_id` 挂在班级下（班内分组），或独立跨班。 |
| `StudentGroupMember` | `(user_id, group_id)` 唯一 | 一个学生可同时在多个分组。加入子组会连带加入父班级。移出班级会连带移出其子分组。 |
| `PaperAudience` | `(paper_id, group_id)`；可选本行 `opens_at`/`closes_at` | 测验对象。没选中的分组看不见卷。空时间则用试卷窗口。可按组错开。 |
| `ChallengeRun` | `slugs_json`，`current_index`，`status` | 一次闯关抽题冻结。 |
| `Paper` | `slugs_json`，`sections_json` | 组卷冻结题单。 |
| | `items_snapshot_json` | 发布时冻结各题内容；之后题库编辑不改变已发布卷。旧卷回填限制见 `services/snapshots.py`。 |
| | `released_at` | 已发布：学生**能看见卡片**。未发布对学生不可见。 |
| | `opens_at` / `closes_at` | 答题时间段。未到 `opens_at` 不能进、不能下发题目。到点 `closes_at` 强制交卷。 |
| | `duration_minutes` | 发布时由时间段推出来，兼容旧逻辑。 |
| | `grading_started_at` | 老师点过「开始评分」。交卷本身不判分。 |
| | `scores_released_at` | 成绩对学生可见。此前学生端分数全藏。 |
| `PaperAttempt` | `(paper_id, user_id)` 唯一；`status` draft/submitted/**absent** | **开考后**第一次成功 `open` 才建行。开考前不建。指定分组截止未作答 → `absent` 缺考 0 分。 |
| `ItemAnswer` | `(user, context_type, context_id, item_slug, part_id)` | 一问一行。`context_type`=`challenge` 或 `paper`。 |
| `GradeJob` (`services/grade_jobs.py`) | `answer_id` 主键、`generation`、`state`、输入快照、`claim_token`/`lease_until` | SQLite 持久评分任务；与作答更新在同一事务中记录。 |

### `ItemAnswer` 分数（两套，不要再加第三套）

| 列 | 谁写 | 谁不能改 |
| --- | --- | --- |
| `score` / `llm_comment` / `llm_json` | 客观本机或主观模型 | 管理员手改**不**写这里 |
| `override_score` / `override_comment` / `override_by` | 管理员点「记下这个分数」 | 模型再评**不得清空或覆盖** |

有效分：`answers.effective_score` = 有 `override_score` 用它，否则用 `score`。

`status`：`draft` 草稿；`submitted` 已收卷未机评；`pending` 主观在排队；`graded` 机评完且管理员没手改；`overridden` 管理员已手改（模型仍可更新 `score`）。

---

## 3. 两条学生路径

**闯关（立刻判）**：`HomeView` → `POST /api/challenge/start` → `PlayerView` → `submit` 调 `answers.submit_item(..., grade=True)` → 客观当场分，主观 `enqueue`。

**试卷（先收卷，老师再评）**：

```text
assemble（released_at 空）
  → 老师选分组、设 opens_at/closes_at 并 release（只有这些分组看见卡片）
  → 未到该生所在分组的 opens_at：卡片可看，open/item 403，不下发 slugs/题目
  → 窗口内：open 建 PaperAttempt，自动保存，单选跳下一题
  → 未全部保存不能主动交卷；该分组 closes_at 到了可强制收卷
  → 交卷只 collect，不 grade
  → 全部对象窗口都截止后才能 start-grade（闯关提交本题仍立刻判）
  → start-grade → 已截止分组里未作答的记缺考 0 分（不进模型），再 machine_grade_*
  → 所有对象窗口都截止，且已交/缺考每一问都 graded/overridden 后才能 release-scores
  → 管理员只在测验匿名答卷里改主观分
  → 发布成绩后，学生页才能点进该生这一次看作答
```

---

## 4. 后端：服务层

### `services/answers.py` — 作答与分数

| 函数 | 做什么 |
| --- | --- |
| `get_or_create_answer` | 取/建一行草稿。 |
| `admin_touched` | `override_score is not None`。 |
| `effective_score` / `effective_comment` | 最终分、最终评语。 |
| `apply_llm_score` | 只写机评列。有手改则 `status=overridden`。 |
| `save_draft` | 试卷/闯关自动保存。 |
| `collect_item` | 收卷：标 `submitted`，**不判**。 |
| `machine_grade_row` / `machine_grade_item` | 客观 `grade_objective`；主观入队。不碰 override。跳过 draft。 |
| `submit_item(..., grade=)` | 闯关 `grade=True`；试卷交卷 `grade=False`。 |
| `grade_paper_attempts` | 老师「开始/再评」：所有已交卷走机评。 |
| `item_is_saved` / `paper_save_progress` | 该题是否已有草稿行；未保存完不能主动交卷。 |
| `scores_visible_for_paper` | 看 `scores_released_at`。 |
| `paper_ungraded_count` / `paper_can_release_scores` | 已截止对象是否全部机评完（含模型、缺考）。窗口没齐或未出齐不能发成绩。 |
| `settle_closed_groups` | 已截止分组：无答卷 → `absent` 且主观 0 分不进模型；草稿强制收。 |
| `item_state` | 一题给学生/播放器。`reveal=False` 藏分。 |
| `score_context` | 一次作答总分（有效分）。 |

### `services/timing.py` — 窗口与卡片状态

| 函数 | 做什么 |
| --- | --- |
| `utc_naive` / `utc_iso` | 时区。 |
| `paper_released` / `paper_opens_at` / `paper_closes_at` | 发布、开考、截止。可按 `PaperAudience` 覆盖。无 `closes_at` 时退回 `opens_at + duration_minutes`。 |
| `audience_for_user` / `paper_visible_to` | 学生是否属于测验对象分组（可多组）。无 audience 的旧卷仍对所有人可见。 |
| `paper_window` | `unpublished` / `waiting` / `open` / `closed`。 |
| `paper_can_enter` | 仅 `open`。 |
| `paper_expired` | 已 `closed`（到点强制交卷）。 |
| `paper_all_windows_closed` | 所有对象分组都已截止。 |
| `paper_can_start_grade` | 试卷已发布且全部窗口已截止才为真。没有截止时间的旧作业仍可评。闯关不走这里。 |
| `paper_flow` / `timing_fields` | 管理端/学生卡片用的标签、倒计时、ISO 时间。含 `can_start_grade`。 |
| `paper_scripts` | 匿名答卷列表（哈希打乱，无姓名；含缺考）。 |
| `paper_ranking` | 带姓名的榜，给学生个人页用，不要用在试卷卡片上。 |

### `services/groups.py` — 班级与分组

| 函数 | 做什么 |
| --- | --- |
| `group_label` / `group_row` / `list_groups` | 班级「七年级1班」；班内分组「七年级1班 / 竞赛组」。 |
| `ungrouped_count` / `group_students` | 未进任何组的人数；某组或未分组花名册。 |
| `require_group` / `user_group_ids` | 取组；该生所在全部 `group_id`。 |
| `student_public` / `teacher_label` | 档案：真名（默认登录名）、年级、`groups[]`、`class_label`、`self_registered`。`teacher_label` 给管理端展示真名。 |
| `add_membership` / `set_memberships` / `remove_membership` | 多对多。加入子组连带父班级；移出班级连带其子组。 |
| `roster_for_paper` | 任一对象分组的成员**并集**（测验花名册，含缺考对象）。 |
| `audience_payload` | 管理端发布对象列表。 |

### 其它服务

| 文件 | 关键函数 | 做什么 |
| --- | --- | --- |
| `grade.py` | `grade_objective` | 选择、填空、数值本机比对。填空规则见 `.cursor/rules/formula-blanks.mdc`。 |
| `grade_jobs.py` | `GradeJob` / `enqueue` / `start_worker` | 持久队列，提交事务内保存题目/作答输入快照；worker 以租约领取任务，重启后续跑。旧版没有任务记录的 pending 作答只在能从当前题库找到对应题目时尝试回填。结果写回前核对作答、评分和人工分状态，旧任务不能覆盖新状态。批量重试跳过已有人工分。 |
| `llm.py` | `grade_part_attempt` | 调 OpenAI 兼容接口评一问；分项与总分严格校验，错误结构作为失败处理，不截断成正式分。含图作答一次携带全部照片，失败不退回纯文字。 |
| `snapshots.py` | `freeze_paper` / `paper_item` / `backfill_legacy_papers` | 发布时冻结题目。旧版已发布卷用升级时题库尽力回填；缺 slug 或小问 ID/分值冲突时将该题写为不可还原、保留作答分数。仅凭旧库无法识别题干/答案改变但 slug 和结构未变的情况。 |
| `review.py` | `review_challenge` / `review_paper` | 闯关带姓名、可改判。试卷默认匿名可改判；`named=True` 给学生页只读。 |
| `bank.py` | `Bank` / `Item` / `Part` | 先读 `bank/` 再读 `data/local-bank/`，同 slug 本机覆盖。内存对象，不是 ORM。 |
| `ingest.py` | `items_from_text` / `items_from_zip` / `save_item` | YAML/ZIP 安全解析与校验；单次输入与 ZIP 展开后均不超过 2 MB，最多 100 题/ZIP 条目；slug 冲突拒绝、不覆盖；只有确认导入才写本机 YAML。 |
| `curriculum.py` | `lookup` | 按科目、1～9/10～12 年级定位课标 Markdown，检索正文页，返回源路径、PDF 页码和原文。义务教育数学按“小学部分/初中部分”和第一至第四学段切片，跨页保持所属学段；不借初中内容给小学出题。缺库或无匹配时拒绝出题；小学物化生史不直接套初中课标。 |
| `generation.py` | `generate` / `validate` | 读取课标原文，使用统一模型配置生成题目；校验元数据、选项、答案、分值和评分细则后返回预览，不写题库。模型可返回依据不足/超学段错误，不强制编题。 |
| `blank.py` | `normalize` / `equivalent_blank` / `numeric_value` | 填空写法规范化；保留大小写与英文词间空格，区分化学上下标，规范英语词中的直/弯撇号。数学、物理、化学的有限数值式用受限 AST 与 Fraction 精确比较；`numeric` 也接受分数、百分数和科学记数，再按原有容差比较。不执行输入代码，不做任意代数化简。 |
| `paper_layout.py` | `paper_layout` / `heading_for_slug` | 组卷大题标题。 |
| `scores.py` | `scores_by_tag` | 按知识点汇总。学生自己看用登录名；老师看用真名。 |
| `access.py` | `sees_subject` / `scoped_subjects` | 老师只看见自己科目。 |

---

## 5. 后端：路由

未登录 401（`deps.get_current_user`）。管理接口 `get_admin_user`。

### `api/auth.py` — `/api/auth`

`status`（是否管理员站点）、`register`（8091 才可能是 admin）、`login`、`logout`、`me`。学生的 `me`/`login`/`register` 不带真名。

### `api/student.py` — `/api`

| 路由 | 函数 | 做什么 |
| --- | --- | --- |
| `GET /home` | `home` | 闯关筛选元数据 + **已发布且该生所在分组**的试卷卡片（含 waiting，不含题目）。 |
| `GET /scores` | `my_scores` | 自己的闯关/试卷。试卷未发成绩则分数为 null。 |
| `GET /scores/by-tag` | `my_scores_by_tag` | 按标签。 |
| `GET /challenge/pool` | `challenge_pool` | 符合条件的题量。 |
| `POST /challenge/start` | `start_challenge` | 抽题或 resume。 |
| `GET /challenge/{id}` | `get_challenge` | 进度。 |
| `GET .../item/{index}` | `challenge_item` | 一题，立刻可揭示分数。 |
| `PUT .../draft` | `challenge_draft` | 自动保存。 |
| `POST .../submit` | `challenge_submit` | `submit_item(grade=True)`。 |

### `api/papers.py` — `/api/papers`

| 路由 | 函数 | 做什么 |
| --- | --- | --- |
| `POST /{id}/open` | `open_paper` | 未发布 / 非对象分组 / 未开考 403 且**不建 attempt**。窗口内才建。截止且无答卷 403。缺考不能再进。 |
| `GET /attempts/{id}` | `get_attempt` | 答题卡。未开考 403，不下发题目。 |
| `GET .../item/{slug}` | `paper_item` | 一题 + `sheet` 题号。分数看 `scores_released_at`。 |
| `PUT .../draft` | `paper_draft` | 自动保存，返回更新后的题号卡。 |
| `POST .../submit` | `paper_submit` | 未截止且未全部保存 → 400。截止可强制收。`grade=False`。 |

内部：`_deny_before_open(paper, user)`（含 `paper_visible_to`）、`_sheet`、`_force_submit`、`_maybe_expire`（按该生 audience）、`_payload`。

### `api/parent.py` — `/api/parent`

科目检查：`_need_subject`。`_apply_window` 校验结束晚于开始，并回写 `duration_minutes`。`_apply_audiences` 要求至少一组，可写每组单独时间。

请求体：`GroupIn`（`name`、`kind`、`grade`、`parent_id`）；`MemberIn`（`student_id`）；`StudentIn` / `StudentPatchIn`（`display_name`、`grade`、`group_ids`）；`PaperWindowIn.audiences`。

| 路由 | 函数 | 做什么 |
| --- | --- | --- |
| `GET /meta` | `meta` | 组卷/加题下拉。 |
| `GET /progress` | `progress` | 学生卡片（含班级/分组标签）。未发成绩的试卷不计入总分、不含答案。 |
| `GET /groups` | `get_groups` | `{ groups, ungrouped }`。 |
| `POST /groups` | `add_group` | 新建班级或分组。保存后列表立刻能看见。 |
| `GET /groups/ungrouped` | `get_ungrouped` | 未进任何组的学生。须写在 `/{id}` 前面。 |
| `GET /groups/{id}` | `get_group` | 组信息 + 组内学生。 |
| `POST /groups/{id}/members` | `add_group_member` | 把已有学生加进该组（不踢出其它组）。 |
| `DELETE /groups/{id}/members/{student_id}` | `remove_group_member` | 移出该组。 |
| `GET /students` | `list_students` | 全部学生（含 `group_ids`）。 |
| `POST /students` | `add_student` | 代开。`group_ids` 可多选。 |
| `PUT /students/{id}` | `update_student` | 改真名、年级、分组。**不改登录名。** 真名留空则回到登录名。自注册学生也能改真名。 |
| `GET /students/{id}/work` | `student_work` | 该生闯关+试卷。试卷未发成绩则无分数、不能点进作答。 |
| `GET /students/{id}/work/paper/{attempt_id}` | `student_paper_review` | 成绩发布后才给带姓名的只读答卷。未发布 403。 |
| `GET /review/challenge/{id}` | `review_run` | 有姓名，属学生区。 |
| `GET /review/paper/{id}` | `review_attempt` | 匿名答卷，属测验区，可改判。 |
| `POST /assemble` | `assemble` | 抽题建 `Paper`，**不**设 `released_at`。 |
| `GET /papers` | `list_papers` | 测验列表。含 `ungraded` / `can_release_scores`。 |
| `GET /papers/{id}` | `paper_detail` | 匿名 `scripts` + 时间窗 + `audiences` + 能否发成绩。 |
| `POST /papers/{id}/release` | `release_paper` | body=`PaperWindowIn`（含 `audiences`）。须至少选一个分组。 |
| `POST /papers/{id}/window` | `set_paper_window` | 开考前可改窗；已开考不能把开始改到未来；评分后不能改。 |
| `POST /papers/{id}/start-grade` | `start_grade` | 须 `paper_can_start_grade`（全部截止）。`settle_closed_groups` 再机评。可重复点。 |
| `POST /papers/{id}/release-scores` | `release_scores` | 须已开始评分，且 `paper_ungraded_count==0`。 |
| `GET/PUT /items` | 题库列表/编辑 | 写本机 yaml。 |
| `POST /ingest/paste` `POST /ingest/file` | 粘贴/文件导入 | `preview=true` 返回候选题、不写入；确认时重新校验，重复 slug 返回 409；单次不超过 2 MB、最多 100 题，ZIP 展开总量不超过 2 MB。 |
| `POST /items/plain` | 白话加题 | 校验后保存本机题库。 |
| `POST /bank/update` | `update_bank` | 只调用 `bank.reload()` 重读当前主机的 `bank/` 与 `data/local-bank/`；不运行 Git、不联网。 |
| `POST /items/generate` | `generate_items` | 管理员按科目、年级、难度、题型、题数（1～5）和 `topic` 出题；受科目权限限制。返回编辑格式题目、课标源路径/页码及学段提示。 |
| `POST /items/generated/save` | `save_generated_item` | 校验编辑后的单题，确认后写本机题库。服务端生成安全 slug，独占创建文件，重复编号返回 409，避免覆盖已有题。 |
| `GET /answers/{id}` `POST /grade` | 改判/显式重评 | 手改分写 `override_*`；主观题可在合法评分阶段显式 `regrade=true`，只更新模型参考分，人工最终分不变。客观题与成绩已发布的试卷不能重评。 |
| `POST /grade/retry-pending` | `retry_pending` | 仅重试可评分的待评主观题；自动跳过已有人工分的作答。 |
| `GET /answers/{id}/grade-job` | `get_grade_job` | 管理员按匿名作答 ID 查看 `queued/running/done/failed/cancelled` 状态与分数，不返回学生姓名。 |
| `GET /queue` | `queue` | 残留接口；未发成绩的试卷作答不进队列。 |
| `GET/POST /llm` `POST /llm/test` | 统一模型配置 | 出题和判题共用地址、密钥、模型、思考配置；密钥不回前端。 |

### `api/uploads.py` — `/api/uploads`

拍演算纸。登录后可读 `/file/{name}`；每问最多 3 张 JPEG/PNG/WebP，每张不超过 6 MB。文件只向作答本人或有权查看该科目的管理员开放。

---

## 6. 前端

路由：`frontend/src/router.ts`。未登录进 `/login`。`api.ts` 带 cookie。管理端分组：`/admin/accounts`（列表+新建+代开）、`/admin/accounts/group/:groupId`、`/admin/accounts/ungrouped`、`/admin/student/:studentId`（档案）。

| 文件 | 页面 | 要点 |
| --- | --- | --- |
| `LoginView.vue` | 登录/注册 | `/api/auth/*` |
| `HomeView.vue` | 闯关筛选 | `/home` `/challenge/pool` `/challenge/start` |
| `StudentPapersView.vue` | 试卷卡片 | `/home`；`can_enter` 才 `open`。waiting/closed 只展示时间，不请求题目。 |
| `PaperView.vue` | 答题卡 + 交卷 | 题号卡 `SheetNav`；未保存完交卷按钮禁用。 |
| `PlayerView.vue` | 作答 | 闯关或试卷同一页。自动保存；路由离开前 flush，页面隐藏/pagehide 时尝试保存，未完成的页面离开会提示。网络写入失败时在 `localStorage` 按用户 ID、作答上下文和题目保存文字草稿，可在同账号同设备显式恢复；图片已上传到服务端，不进入本地文字备份。 |
| `ResultView.vue` | 闯关结果 | |
| `ScoresView.vue` | 我的成绩 | 未公布显示 — |
| `ParentView.vue` | 管理多 Tab | 学生/测验/组卷/题库/加题/模型/学生账号。账号页：已有分组卡片、新建分组（班级 / 班内 / 其它）、代开（可多选组）。外部题包先预览再确认；重复 slug 不覆盖。「重新读取本机题库」仅刷新本机题库。 |
| `AdminGroupView.vue` | 一个分组 | 组内学生卡片 → 学生档案；可把已有学生加进来、代开进本组。 |
| `AdminPaperView.vue` | 一份测验 | 选分组、设时间窗（可错开）、发布、截止后开始评分、匿名答卷改判。未截止「开始评分」禁用。未出齐分「发布成绩」禁用。 |
| `AdminStudentView.vue` | 一名学生 | 登录名只读。可改真名/年级/多个分组。真名学生看不到。闯关可点；试卷未发成绩不能看作答，不跳进测验。 |
| `AdminAttemptView.vue` | 一份作答 | 测验路径匿名可改判；学生路径发布后只读。 |
| `AdminItemView.vue` | 改题 | `ItemPartEditor` |
| `GenerateQuestions.vue` | 加题页的 AI 出题 | 选择科目、年级、难度、题型、题数，描述知识点；显示来源页码，编辑题干/答案后逐题确认入库。模型配置链接指向同一 `/admin/llm`；聊天导入与手工加题收在折叠区。 |
| `GradeBox.vue` | 改判 | 管理员分可改；模型分只读参考；再评不覆盖手改 |
| `SheetNav.vue` | 题号卡 | `pick` 跳题 |
| `TimezoneBar.vue` | 顶栏时区下拉 | 默认北京，可改；`localStorage` 记住 |
| `timeZone.ts` | 时区换算 | 墙上时间 ↔ UTC；夏令时靠 Intl |
| `FormulaField.vue` | 填空公式按钮 | 仅数理化生 |

样式：`frontend/src/style.css`（`.sheet-n` 题号、`.card.locked` 未开考卡片、`.tz-select` 时区下拉）。

---

## 7. 改需求时动哪里

| 你想改 | 优先文件 |
| --- | --- |
| 开考前能否看见卡片/题目 | `timing.paper_window`，`papers.open_paper` / `_deny_before_open`，`student.home`，`StudentPapersView` |
| 测验发给哪些学生 | `StudentGroup` / `StudentGroupMember` / `PaperAudience`，`parent.release_paper` / `_apply_audiences`，`timing.paper_visible_to`，`AdminPaperView` |
| 班级、分组、学生档案 | `services/groups.py`，`parent.get_groups` / `add_group` / `update_student`，`ParentView` 学生账号，`AdminGroupView`，`AdminStudentView` |
| 答题时间段 | `Paper.opens_at/closes_at`，`PaperAudience`，`parent.release_paper` / `set_paper_window`，`AdminPaperView`，`timeZone.ts` |
| 时区显示/填写 | `timeZone.ts`，`TimezoneBar.vue`，`AdminPaperView`，`StudentPapersView`，`ParentView` |
| 交卷是否立刻判 | `papers.paper_submit` 的 `grade=`，`parent.start_grade`（须截止）。闯关 `student` 提交本题立刻 `submit_item` 判分。 |
| 模型分 vs 老师分 | `answers.apply_llm_score` / `effective_*`，`parent.grade`，`llm` worker，`GradeBox` |
| 能不能发成绩 | `answers.paper_ungraded_count`，`parent.release_scores`，`AdminPaperView` |
| 学生页 vs 测验页 | `AdminStudentView`，`student_paper_review`，`review_paper(named=)` |
| 匿名答卷 | `timing.paper_scripts`，`review.review_paper`，`AdminPaperView` |
| 单选跳转 / 题号卡 / 自动保存 | `PlayerView.vue`，`papers.paper_draft` 返回 `sheet` |
| 未保存完不能交 | `answers.paper_save_progress`，`papers.paper_submit`，`PaperView` |
| 客观题判分规则 | `services/grade.py` |
| 填空等价写法 | `services/blank.py`；`grade_objective(..., subject)` 接收科目，`answers.machine_grade_row` 透传题目科目。候选答案数组表示同一个空的多种可接受写法。 |
| 主观题提示词/JSON | `services/llm.py` |
| AI 出题/课标检索 | `services/generation.py`、`services/curriculum.py`、`parent.generate_items`、`GenerateQuestions.vue`；资料位于 `docs/standards/`，离线检索用 `scripts/lookup_standard.py` |
| 组卷抽题 | `parent.assemble`，`bank.list` |
| 新题型 | `constants.py` + `grade.py` + `PlayerView` + `ItemPartEditor` + 出题 skill |
| SQLite 新列 | `models.py` **和** `db.migrate()` |
| 学生看不见的管理功能 | 只能放 `/api/parent`，依赖 `get_admin_user` |

---

## 8. 不要打破的约定

1. 学生端任何响应不得带同学姓名、名次、别人的分，也不得带自己的真名（`display_name`）。试卷管理卡片用匿名 `答卷 n`。登录名是学生自己注册时的名字，也是学生页顶栏看到的名字。
2. 未到 `opens_at`：不建 `PaperAttempt`，不返回 `slugs`/题干。
3. 试卷交卷不调用模型；只有截止后的 `start-grade` 才机评。闯关「提交本题」立刻判。
4. `apply_llm_score` 与 LLM worker 不得修改 `override_*`。
5. 填空答案不用 LaTeX；公式按钮范围见 workspace 规则 `formula-blanks.mdc`。
6. 改 Vue 后构建 `frontend/dist`，否则 8090 仍是旧页。改 FastAPI 路由后**必须重启 uvicorn**，否则新接口 404，文案就是「找不到这个接口，重启答题服务后再试」。
7. 8090 是未加密 HTTP，只用于可信局域网；8091 默认仅监听 `127.0.0.1`，只供主机本机注册管理员。管理员接口仍需有效登录会话。模型密钥保存在主机且不会返回前端；管理员通过 8090 配置模型，因此不能把服务放到公网或不可信网络。
8. 界面默认北京时间，顶栏一个下拉可改时区；开考仍用主机 UTC，与谁选哪个时区无关。
9. 「学生」不跳进「测验」的匿名答卷。未发成绩：学生页不看该次答案。改判只在测验匿名答卷。
10. `release_scores` 时已截止对象每一问必须已 `graded` 或 `overridden`；有 pending/submitted 就 400，按钮禁用。
11. 班级是分组的一种；分组可挂在班级下。一个学生可同时在多个分组。新发布的测验必须指定分组；组内未作答截止后记缺考 0 分，不进模型。
12. `users.group_id` 是旧列，读写以 `student_group_members` 为准。
13. 试卷「开始评分」必须等全部对象窗口截止；接口 `start_grade` 未截止返回 400。没有截止时间的旧作业除外。闯关提交本题仍立刻判。
14. AI 出题和主观判分共用一处模型配置。生成预览不写库，管理员确认后才保存；不能将模型生成内容当成已经人工核准的题目。
15. 课标 Markdown 保留 PDF 页界与来源。课标按学段规定要求，不能据此断言某个年级某学期已学完；OCR 中不清楚的公式和表格须回查源 PDF。

---

## 9. 本地验证

Python 测试应在隔离数据目录运行，不要让测试读取或写入生产 `data/`。Ubuntu 上可用：

```bash
TEST_ROOT="$(mktemp -d)"
SUBJECT_HUB_ROOT="$PWD" SUBJECT_HUB_DATA="$TEST_ROOT/data" SUBJECT_HUB_BANK="$TEST_ROOT/bank" PYTHONPATH="$PWD/backend" .venv/bin/python -m unittest discover -s tests
(cd frontend && npm ci && npm run typecheck && npm test && npm run build)
```

`scripts/update-from-github.sh` 会在隔离 staging 目录自动执行这些 Python 测试、前端类型检查、测试和构建；全部通过后才停服备份并切换版本。需要 Python 3.10+ 和 Node.js 22.22.2+（22 系列）、24.15+（24 系列）或 26+。当前固定的 Python 直接依赖只在 Windows/Python 3.13.6 验证，Ubuntu 实机验证仍需 CI 补齐。

## 10. 其它文档怎么分工

| 文件 | 管什么 | 不要写什么 |
| --- | --- | --- |
| **本文 `tech.md`** | 文件、函数、表、请求流 | 课标全文、装机步骤 |
| `architecture.md` | 产品口径、题型、题库磁盘格式 | 每个 FastAPI 函数名（易过期） |
| `plan.md` | 当前功能、限制和维护约定 | 当代码地图用 |
| `host.md` | 安装与端口 | 判分细节 |
| `llm-grading.md` | 模型协议与失败行为 | 前端组件树 |
