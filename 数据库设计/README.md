# 数据库设计（分工 5）

“学术课件智能整理与复习 Agent”第二次迭代的数据库设计交付物，负责人：吴雅晴（102402103）。

## 文件说明

| 文件 | 说明 |
| --- | --- |
| 数据库设计说明书_学术课件整理_V1.1.docx | 29 页设计说明书：概念模型、逻辑模型、物理设计、关键决策、验收用例、需求核对响应 |
| schema.sql | MySQL 8.0 建库脚本：13 张表、2 个薄弱度视图、评分存储过程、种子数据、10 条验收查询、增量迁移 |
| er_diagram.png | 图 3-1 数据主干：课件、原文块、笔记与知识点 |
| er_diagram2.png | 图 3-2 学习闭环：卡片、错题、自测与导图 |
| 数据库设计_博客稿.md | 工作内容介绍与需求核对意见处理，可直接用于团队博客 |

## 设计要点

- **一条主线**：`courseware` → `courseware_chunk` → `knowledge_point`，卡片、错题、自测题、导图节点都挂在知识点上，出处可定位到页码与字符区间。
- **版本绑定**：`knowledge_point` 按 `(courseware_id, note_version, kp_code)` 唯一，下游表存 `note_version` 快照，避免新旧版本混用。
- **重复提交防护**：交卷用 `status = 2` 保证只批改一次，`self_test_item.is_backfilled` 保证错题只回填一次。
- **薄弱度双口径**：`v_kp_weakness` 只按错题计分，`v_kp_weakness_ext` 在 A1 确认后叠加卡片遗忘次数。
- **时间统一 UTC**：连接固定 `SET time_zone='+00:00'`，前端按东八区展示。

## 快速验收

```bash
# 需要 MySQL 8.0.16+，并设置 ngram_token_size=2
mysql -h 127.0.0.1 -P 3306 -u root -p < schema.sql
```

```sql
-- 表数量应为 13
SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'course_agent';
-- 评分事务：0 表示成功（到期时间为 UTC）
CALL sp_review_card(2, 1, 3, 3, 2.50, '2026-11-08 20:00:00', 6000, @code);
SELECT @code;
```

验收用例见说明书第 8 章（T01—T12），巡检与核心查询见 `schema.sql` 第 5 节（Q1—Q10）。

> 说明：本轮只在本地做了 SQL 语法解析与结构校验，尚未在 MySQL 实例上执行；T01—T12 需在联调环境跑一遍。
