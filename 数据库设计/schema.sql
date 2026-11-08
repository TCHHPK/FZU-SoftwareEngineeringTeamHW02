-- ============================================================
-- 学术课件整理与复习 Agent · 数据库初始化脚本
-- 团队：天生一队    分工：数据库设计（吴雅晴）
-- 版本：V1.1       日期：2026-11-06
-- 环境：MySQL 8.0.16+（需要 CHECK 约束与 ngram 全文索引）
-- 字符集：utf8mb4 / utf8mb4_0900_ai_ci
-- 时区：库内 DATETIME 一律存 UTC，连接执行 SET time_zone = '+00:00'
--
-- 说明：
--   1. 本脚本用于本地与测试环境“从零重建”，含 13 张表、2 个视图、
--      1 个存储过程、种子数据和 10 条验收查询。
--   2. 生产库请勿执行 DROP 段，改用文件末尾“增量迁移”一节的 ALTER。
--   3. 需在 my.cnf 中设置 ngram_token_size=2 后重启，中文全文检索才生效。
--   4. 种子数据中的时间已按 UTC 写入；北京时间 = UTC + 8 小时。
-- ============================================================

SET NAMES utf8mb4;
SET time_zone = '+00:00';
SET FOREIGN_KEY_CHECKS = 0;

CREATE DATABASE IF NOT EXISTS `course_agent` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE `course_agent`;

-- ---------- 0. 重建（仅测试环境） ----------
DROP TABLE IF EXISTS `mindmap_node`;
DROP TABLE IF EXISTS `self_test_item`;
DROP TABLE IF EXISTS `self_test`;
DROP TABLE IF EXISTS `wrong_question`;
DROP TABLE IF EXISTS `review_log`;
DROP TABLE IF EXISTS `flashcard`;
DROP TABLE IF EXISTS `qa_record`;
DROP TABLE IF EXISTS `knowledge_point`;
DROP TABLE IF EXISTS `note_section`;
DROP TABLE IF EXISTS `note`;
DROP TABLE IF EXISTS `courseware_chunk`;
DROP TABLE IF EXISTS `courseware`;
DROP TABLE IF EXISTS `sys_user`;
SET FOREIGN_KEY_CHECKS = 1;

-- ---------- 1. 建表（13 张） ----------
-- 用户表：存登录账号与基本资料，是所有学习数据的所有者。
CREATE TABLE IF NOT EXISTS `sys_user` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '用户主键',
  `username` VARCHAR(50) NOT NULL COMMENT '登录名，全局唯一',
  `password_hash` VARCHAR(100) NOT NULL COMMENT 'bcrypt 摘要，不存明文',
  `nickname` VARCHAR(50) NOT NULL DEFAULT '' COMMENT '显示昵称',
  `email` VARCHAR(120) NULL DEFAULT NULL COMMENT '邮箱，可空；用于找回密码',
  `status` TINYINT NOT NULL DEFAULT 1 COMMENT '1 正常，0 禁用',
  `last_login_at` DATETIME NULL DEFAULT NULL COMMENT '最近登录时间',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '注册时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_username` (`username`),
  UNIQUE KEY `uk_email` (`email`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='用户表';

-- 课件表：一次上传对应一条记录，保存文件元信息与解析状态。
CREATE TABLE IF NOT EXISTS `courseware` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '课件主键',
  `user_id` BIGINT UNSIGNED NOT NULL COMMENT '上传者，归属校验的第一道条件',
  `title` VARCHAR(200) NOT NULL COMMENT '课件标题，默认取文件名去扩展名',
  `course_name` VARCHAR(100) NULL DEFAULT NULL COMMENT '课程名，如“机器学习”，可空',
  `file_name` VARCHAR(255) NOT NULL COMMENT '原始文件名',
  `file_type` VARCHAR(16) NOT NULL COMMENT 'pptx / pdf / docx 等',
  `file_size` BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '字节数',
  `storage_path` VARCHAR(500) NOT NULL COMMENT '对象存储相对路径，不存公网 URL',
  `page_count` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '页数，解析后回填',
  `parse_status` TINYINT NOT NULL DEFAULT 0 COMMENT '0 待解析 1 解析中 2 成功 3 失败',
  `parse_error` VARCHAR(500) NULL DEFAULT NULL COMMENT '失败原因摘要',
  `uploaded_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '上传时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `deleted_at` DATETIME NULL DEFAULT NULL COMMENT '软删除时间；NULL 表示未删除',
  PRIMARY KEY (`id`),
  KEY `idx_user_deleted` (`user_id`, `deleted_at`),
  KEY `idx_parse_status` (`parse_status`),
  CONSTRAINT `fk_courseware_user` FOREIGN KEY (`user_id`) REFERENCES `sys_user` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='课件表';

-- 课件原文块表：把课件切成可定位的最小原文单元，是所有“出处”的物理落点。
CREATE TABLE IF NOT EXISTS `courseware_chunk` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '原文块主键，即“出处 ID”',
  `courseware_id` BIGINT UNSIGNED NOT NULL COMMENT '所属课件',
  `page_no` INT UNSIGNED NOT NULL COMMENT '页码，从 1 开始',
  `chunk_index` INT UNSIGNED NOT NULL COMMENT '页内序号，从 1 开始',
  `content_type` TINYINT NOT NULL DEFAULT 1 COMMENT '★1 文本 2 公式 3 表格 4 图注 5 代码',
  `content` MEDIUMTEXT NOT NULL COMMENT '纯文本内容；公式块存 LaTeX 源码的可读形式',
  `latex` TEXT NULL DEFAULT NULL COMMENT '★公式块的 LaTeX 源码，非公式块为 NULL',
  `image_path` VARCHAR(500) NULL DEFAULT NULL COMMENT '★图注/表格截图路径，可空',
  `char_start` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '★在整页文本中的起始字符偏移',
  `char_end` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '★结束偏移（左闭右开）',
  `token_count` INT UNSIGNED NULL DEFAULT NULL COMMENT '切块 token 数，供上下文窗口预算',
  `embedding_ref` VARCHAR(100) NULL DEFAULT NULL COMMENT '★向量库主键，向量本身不落 MySQL',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '入库时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_course_page_chunk` (`courseware_id`, `page_no`, `chunk_index`),
  FULLTEXT KEY `ft_chunk_content` (`content`) WITH PARSER ngram,
  CONSTRAINT `fk_chunk_courseware` FOREIGN KEY (`courseware_id`) REFERENCES `courseware` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='课件原文块表';

-- 结构化笔记表：一份课件对应一份结构化笔记，保留版本号以支持重新整理。
CREATE TABLE IF NOT EXISTS `note` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '笔记主键',
  `courseware_id` BIGINT UNSIGNED NOT NULL COMMENT '来源课件',
  `user_id` BIGINT UNSIGNED NOT NULL COMMENT '所有者',
  `title` VARCHAR(200) NOT NULL COMMENT '笔记标题',
  `summary` TEXT NULL DEFAULT NULL COMMENT '全文摘要',
  `status` TINYINT NOT NULL DEFAULT 1 COMMENT '0 草稿 1 已发布',
  `version` INT UNSIGNED NOT NULL DEFAULT 1 COMMENT '重新整理时递增，旧版本保留',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_course_version` (`courseware_id`, `version`),
  KEY `idx_user_updated` (`user_id`, `updated_at`),
  CONSTRAINT `fk_note_courseware` FOREIGN KEY (`courseware_id`) REFERENCES `courseware` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT,
  CONSTRAINT `fk_note_user` FOREIGN KEY (`user_id`) REFERENCES `sys_user` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='结构化笔记表';

-- 笔记章节表：按标题树存笔记正文，parent_id 自关联形成章节层级。
CREATE TABLE IF NOT EXISTS `note_section` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '章节主键',
  `note_id` BIGINT UNSIGNED NOT NULL COMMENT '所属笔记',
  `parent_id` BIGINT UNSIGNED NULL DEFAULT NULL COMMENT '父章节；顶层为 NULL',
  `heading` VARCHAR(200) NOT NULL COMMENT '章节标题',
  `level` TINYINT NOT NULL COMMENT '层级 1—4',
  `content_md` MEDIUMTEXT NOT NULL COMMENT 'Markdown 正文',
  `order_no` INT NOT NULL COMMENT '同级排序号',
  `page_from` INT UNSIGNED NULL DEFAULT NULL COMMENT '对应起始页',
  `page_to` INT UNSIGNED NULL DEFAULT NULL COMMENT '对应结束页',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (`id`),
  KEY `idx_note_order` (`note_id`, `order_no`),
  CONSTRAINT `fk_section_note` FOREIGN KEY (`note_id`) REFERENCES `note` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT,
  CONSTRAINT `fk_section_parent` FOREIGN KEY (`parent_id`) REFERENCES `note_section` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='笔记章节表';

-- 知识点表：全库的知识枢纽：卡片、错题、自测题、导图节点都挂在它上面，并回指原文块。
CREATE TABLE IF NOT EXISTS `knowledge_point` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '知识点主键',
  `courseware_id` BIGINT UNSIGNED NOT NULL COMMENT '所属课件（知识点的作用域）',
  `note_id` BIGINT UNSIGNED NULL DEFAULT NULL COMMENT '生成它的笔记，可空',
  `note_version` INT UNSIGNED NOT NULL DEFAULT 1 COMMENT '所属笔记版本；重新整理时递增，版本内的知识点独立成行',
  `source_chunk_id` BIGINT UNSIGNED NULL DEFAULT NULL COMMENT '主要出处原文块，可空',
  `kp_code` VARCHAR(50) NOT NULL COMMENT '业务编码，如 KP-7-2-1',
  `chapter` VARCHAR(100) NULL DEFAULT NULL COMMENT '章节名，薄弱点按它聚合',
  `title` VARCHAR(200) NOT NULL COMMENT '知识点名称',
  `summary` TEXT NULL DEFAULT NULL COMMENT '一句话解释，可直接做卡片背面',
  `difficulty` TINYINT NOT NULL DEFAULT 3 COMMENT '难度 1—5，供组卷配比',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_course_kpcode` (`courseware_id`, `note_version`, `kp_code`),
  KEY `idx_course_chapter` (`courseware_id`, `chapter`),
  KEY `idx_source_chunk` (`source_chunk_id`),
  CONSTRAINT `fk_kp_courseware` FOREIGN KEY (`courseware_id`) REFERENCES `courseware` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT,
  CONSTRAINT `fk_kp_note` FOREIGN KEY (`note_id`) REFERENCES `note` (`id`) ON DELETE SET NULL ON UPDATE RESTRICT,
  CONSTRAINT `fk_kp_chunk` FOREIGN KEY (`source_chunk_id`) REFERENCES `courseware_chunk` (`id`) ON DELETE SET NULL ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='知识点表';

-- AI 问答记录表：保留每次提问、回答与引用块，既做历史记录，也做错题来源。
CREATE TABLE IF NOT EXISTS `qa_record` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '问答主键',
  `user_id` BIGINT UNSIGNED NOT NULL COMMENT '提问者',
  `courseware_id` BIGINT UNSIGNED NOT NULL COMMENT '限定课件范围',
  `question` TEXT NOT NULL COMMENT '用户问题',
  `answer` MEDIUMTEXT NOT NULL COMMENT '带引用的回答',
  `cited_chunk_ids` JSON NOT NULL COMMENT '引用块 ID 数组，如 [12,15]',
  `confidence` DECIMAL(4,3) NULL DEFAULT NULL COMMENT '置信度 0—1，可空',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '提问时间',
  PRIMARY KEY (`id`),
  KEY `idx_user_time` (`user_id`, `created_at`),
  KEY `idx_course_time` (`courseware_id`, `created_at`),
  CONSTRAINT `fk_qa_user` FOREIGN KEY (`user_id`) REFERENCES `sys_user` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `fk_qa_courseware` FOREIGN KEY (`courseware_id`) REFERENCES `courseware` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='AI 问答记录表';

-- 记忆卡片表：存卡片内容与 SM-2 复习参数，是 A1 记忆卡片的主表。
CREATE TABLE IF NOT EXISTS `flashcard` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '卡片主键',
  `user_id` BIGINT UNSIGNED NOT NULL COMMENT '卡片所有者',
  `knowledge_point_id` BIGINT UNSIGNED NOT NULL COMMENT '关联知识点',
  `courseware_id` BIGINT UNSIGNED NOT NULL COMMENT '冗余课件 ID，支持按课件筛卡',
  `note_version` INT UNSIGNED NOT NULL DEFAULT 1 COMMENT '建卡时的笔记版本快照，与 knowledge_point.note_version 一致',
  `card_type` TINYINT NOT NULL COMMENT '1 问答卡 2 填空卡',
  `front` TEXT NOT NULL COMMENT '正面：问题或挖空句',
  `back` TEXT NOT NULL COMMENT '背面：答案',
  `source_chunk_id` BIGINT UNSIGNED NULL DEFAULT NULL COMMENT '出处原文块，可空',
  `source_page` INT UNSIGNED NULL DEFAULT NULL COMMENT '出处页码，展示用冗余',
  `state` TINYINT NOT NULL DEFAULT 0 COMMENT '0 新卡 1 学习中 2 复习中 3 暂停',
  `ease_factor` DECIMAL(4,2) NOT NULL DEFAULT 2.50 COMMENT 'SM-2 难度因子 EF，1.30—5.00',
  `interval_days` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '当前复习间隔（天）',
  `repetitions` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '连续答对次数',
  `lapses` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '遗忘次数，薄弱度输入之一',
  `due_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '下次到期时间，今日待复习的排序键',
  `last_reviewed_at` DATETIME NULL DEFAULT NULL COMMENT '最近复习时间',
  `origin` TINYINT NOT NULL DEFAULT 1 COMMENT '1 笔记生成 2 错题生成 3 手动新建',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `deleted_at` DATETIME NULL DEFAULT NULL COMMENT '软删除时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_user_kp_type` (`user_id`, `knowledge_point_id`, `card_type`),
  KEY `idx_user_due` (`user_id`, `state`, `due_at`),
  KEY `idx_kp` (`knowledge_point_id`),
  KEY `idx_courseware` (`courseware_id`),
  CONSTRAINT `fk_card_user` FOREIGN KEY (`user_id`) REFERENCES `sys_user` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `fk_card_kp` FOREIGN KEY (`knowledge_point_id`) REFERENCES `knowledge_point` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT,
  CONSTRAINT `fk_card_courseware` FOREIGN KEY (`courseware_id`) REFERENCES `courseware` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT,
  CONSTRAINT `fk_card_chunk` FOREIGN KEY (`source_chunk_id`) REFERENCES `courseware_chunk` (`id`) ON DELETE SET NULL ON UPDATE RESTRICT,
  CONSTRAINT `ck_card_ease` CHECK (`ease_factor` BETWEEN 1.30 AND 5.00)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='记忆卡片表';

-- 复习记录表：追加式记录每一次四档评分及前后参数，用于遗忘曲线与薄弱度计算。
CREATE TABLE IF NOT EXISTS `review_log` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '记录主键',
  `card_id` BIGINT UNSIGNED NOT NULL COMMENT '被评分的卡片',
  `user_id` BIGINT UNSIGNED NOT NULL COMMENT '复习者',
  `rating` TINYINT NOT NULL COMMENT '1 忘记 2 困难 3 一般 4 熟练',
  `prev_interval_days` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '评分前间隔',
  `next_interval_days` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '评分后间隔',
  `prev_ease` DECIMAL(4,2) NOT NULL DEFAULT 2.50 COMMENT '评分前 EF',
  `next_ease` DECIMAL(4,2) NOT NULL DEFAULT 2.50 COMMENT '评分后 EF',
  `duration_ms` INT UNSIGNED NULL DEFAULT NULL COMMENT '停留毫秒，可空',
  `reviewed_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '复习时间',
  PRIMARY KEY (`id`),
  KEY `idx_card_time` (`card_id`, `reviewed_at`),
  KEY `idx_user_time` (`user_id`, `reviewed_at`),
  CONSTRAINT `fk_log_card` FOREIGN KEY (`card_id`) REFERENCES `flashcard` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT,
  CONSTRAINT `fk_log_user` FOREIGN KEY (`user_id`) REFERENCES `sys_user` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `ck_log_rating` CHECK (`rating` BETWEEN 1 AND 4)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='复习记录表';

-- 错题表：汇总 AI 问答与自测中答错的题，按知识点与状态支持筛选、重做。
CREATE TABLE IF NOT EXISTS `wrong_question` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '错题主键',
  `user_id` BIGINT UNSIGNED NOT NULL COMMENT '所有者',
  `knowledge_point_id` BIGINT UNSIGNED NULL DEFAULT NULL COMMENT '关联知识点，可空',
  `courseware_id` BIGINT UNSIGNED NULL DEFAULT NULL COMMENT '所属课件；课件删除后置空，保留错题历史',
  `note_version` INT UNSIGNED NOT NULL DEFAULT 1 COMMENT '收录时的笔记版本快照',
  `source_type` TINYINT NOT NULL COMMENT '1 AI 问答 2 自测 3 手动',
  `source_id` BIGINT UNSIGNED NULL DEFAULT NULL COMMENT '来源记录 ID，手动录入为 NULL',
  `question_type` TINYINT NULL DEFAULT NULL COMMENT '1 单选 2 多选 3 填空 4 简答 5 问答',
  `stem` TEXT NOT NULL COMMENT '题干',
  `user_answer` TEXT NULL DEFAULT NULL COMMENT '当时的错误答案',
  `correct_answer` TEXT NOT NULL COMMENT '正确答案',
  `analysis` MEDIUMTEXT NULL DEFAULT NULL COMMENT '解析',
  `source_chunk_id` BIGINT UNSIGNED NULL DEFAULT NULL COMMENT '出处原文块，可空',
  `source_page` INT UNSIGNED NULL DEFAULT NULL COMMENT '出处页码',
  `wrong_count` INT UNSIGNED NOT NULL DEFAULT 1 COMMENT '累计答错次数',
  `status` TINYINT NOT NULL DEFAULT 0 COMMENT '0 未掌握 1 复习中 2 已掌握',
  `last_wrong_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '最近答错时间',
  `mastered_at` DATETIME NULL DEFAULT NULL COMMENT '标记掌握时间',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '收录时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_user_source` (`user_id`, `source_type`, `source_id`),
  KEY `idx_user_status` (`user_id`, `status`, `last_wrong_at`),
  KEY `idx_kp` (`knowledge_point_id`),
  CONSTRAINT `fk_wq_user` FOREIGN KEY (`user_id`) REFERENCES `sys_user` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `fk_wq_kp` FOREIGN KEY (`knowledge_point_id`) REFERENCES `knowledge_point` (`id`) ON DELETE SET NULL ON UPDATE RESTRICT,
  CONSTRAINT `fk_wq_courseware` FOREIGN KEY (`courseware_id`) REFERENCES `courseware` (`id`) ON DELETE SET NULL ON UPDATE RESTRICT,
  CONSTRAINT `fk_wq_chunk` FOREIGN KEY (`source_chunk_id`) REFERENCES `courseware_chunk` (`id`) ON DELETE SET NULL ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='错题表';

-- 自测表：一次组卷对应一条记录，存范围、题量、得分与状态。
CREATE TABLE IF NOT EXISTS `self_test` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '自测主键',
  `user_id` BIGINT UNSIGNED NOT NULL COMMENT '作答者',
  `courseware_id` BIGINT UNSIGNED NOT NULL COMMENT '所属课件',
  `title` VARCHAR(200) NOT NULL COMMENT '试卷标题',
  `scope` JSON NOT NULL COMMENT '组卷范围，如 {"chapter":"第7章","kp_ids":[1,2]}',
  `question_types` JSON NOT NULL COMMENT '题型数组，如 [1,3]',
  `question_count` SMALLINT NOT NULL DEFAULT 0 COMMENT '题目数',
  `total_score` DECIMAL(6,2) NOT NULL DEFAULT 100.00 COMMENT '总分',
  `score` DECIMAL(6,2) NULL DEFAULT NULL COMMENT '得分，未批改为 NULL',
  `correct_count` SMALLINT NULL DEFAULT NULL COMMENT '答对题数',
  `status` TINYINT NOT NULL DEFAULT 0 COMMENT '0 生成中 1 待作答 2 已交卷 3 批改完成 4 生成失败',
  `started_at` DATETIME NULL DEFAULT NULL COMMENT '开始作答时间',
  `submitted_at` DATETIME NULL DEFAULT NULL COMMENT '交卷时间',
  `duration_sec` INT UNSIGNED NULL DEFAULT NULL COMMENT '作答耗时（秒）',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (`id`),
  KEY `idx_user_time` (`user_id`, `created_at`),
  KEY `idx_courseware` (`courseware_id`),
  CONSTRAINT `fk_test_user` FOREIGN KEY (`user_id`) REFERENCES `sys_user` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `fk_test_courseware` FOREIGN KEY (`courseware_id`) REFERENCES `courseware` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='自测表';

-- 自测题目表：存每一道题的题干、选项、作答、得分与出处，支撑逐题解析和错题回填。
CREATE TABLE IF NOT EXISTS `self_test_item` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '题目主键',
  `test_id` BIGINT UNSIGNED NOT NULL COMMENT '所属自测',
  `seq_no` SMALLINT NOT NULL COMMENT '卷内题号',
  `question_type` TINYINT NOT NULL COMMENT '1 单选 2 多选 3 填空 4 简答',
  `knowledge_point_id` BIGINT UNSIGNED NULL DEFAULT NULL COMMENT '考查知识点，可空',
  `note_version` INT UNSIGNED NOT NULL DEFAULT 1 COMMENT '组卷时的笔记版本快照',
  `stem` TEXT NOT NULL COMMENT '题干',
  `options` JSON NULL DEFAULT NULL COMMENT '选项数组，主观题/填空题为 NULL',
  `correct_answer` TEXT NOT NULL COMMENT '参考答案',
  `user_answer` TEXT NULL DEFAULT NULL COMMENT '用户作答',
  `is_correct` TINYINT NULL DEFAULT NULL COMMENT '1 正确 0 错误，未批改 NULL',
  `is_backfilled` TINYINT NOT NULL DEFAULT 0 COMMENT '错题是否已回填：1 是 0 否；重复交卷时据此跳过',
  `score` DECIMAL(5,2) NOT NULL DEFAULT 0.00 COMMENT '本题得分',
  `max_score` DECIMAL(5,2) NOT NULL DEFAULT 0.00 COMMENT '本题满分',
  `analysis` MEDIUMTEXT NULL DEFAULT NULL COMMENT '逐题解析',
  `source_chunk_id` BIGINT UNSIGNED NULL DEFAULT NULL COMMENT '出处原文块，可空',
  `source_page` INT UNSIGNED NULL DEFAULT NULL COMMENT '出处页码',
  `answered_at` DATETIME NULL DEFAULT NULL COMMENT '作答时间',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '生成时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_test_seq` (`test_id`, `seq_no`),
  KEY `idx_kp` (`knowledge_point_id`),
  CONSTRAINT `fk_item_test` FOREIGN KEY (`test_id`) REFERENCES `self_test` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT,
  CONSTRAINT `fk_item_kp` FOREIGN KEY (`knowledge_point_id`) REFERENCES `knowledge_point` (`id`) ON DELETE SET NULL ON UPDATE RESTRICT,
  CONSTRAINT `fk_item_chunk` FOREIGN KEY (`source_chunk_id`) REFERENCES `courseware_chunk` (`id`) ON DELETE SET NULL ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='自测题目表';

-- 导图节点表：以邻接表存思维导图节点，parent_id 自关联，可递归拉出整棵树。
CREATE TABLE IF NOT EXISTS `mindmap_node` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '节点主键',
  `courseware_id` BIGINT UNSIGNED NOT NULL COMMENT '所属课件（一张导图）',
  `note_version` INT UNSIGNED NOT NULL DEFAULT 1 COMMENT '生成导图时的笔记版本快照',
  `user_id` BIGINT UNSIGNED NOT NULL COMMENT '所有者',
  `parent_id` BIGINT UNSIGNED NULL DEFAULT NULL COMMENT '父节点；根节点为 NULL',
  `title` VARCHAR(200) NOT NULL COMMENT '节点标题',
  `node_type` TINYINT NOT NULL COMMENT '1 根 2 章 3 节 4 知识点',
  `knowledge_point_id` BIGINT UNSIGNED NULL DEFAULT NULL COMMENT '关联知识点，可空',
  `summary` TEXT NULL DEFAULT NULL COMMENT '节点摘要，点开时展示',
  `source_chunk_id` BIGINT UNSIGNED NULL DEFAULT NULL COMMENT '出处原文块，可空',
  `page_no` INT UNSIGNED NULL DEFAULT NULL COMMENT '出处页码',
  `level` TINYINT NOT NULL COMMENT '层级 1—4',
  `order_no` INT NOT NULL COMMENT '同级排序号',
  `is_collapsed` TINYINT NOT NULL DEFAULT 0 COMMENT '前端默认是否收起：1 是 0 否',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_course_parent` (`courseware_id`, `parent_id`, `order_no`),
  KEY `idx_kp` (`knowledge_point_id`),
  CONSTRAINT `fk_node_courseware` FOREIGN KEY (`courseware_id`) REFERENCES `courseware` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT,
  CONSTRAINT `fk_node_user` FOREIGN KEY (`user_id`) REFERENCES `sys_user` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `fk_node_parent` FOREIGN KEY (`parent_id`) REFERENCES `mindmap_node` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT,
  CONSTRAINT `fk_node_kp` FOREIGN KEY (`knowledge_point_id`) REFERENCES `knowledge_point` (`id`) ON DELETE SET NULL ON UPDATE RESTRICT,
  CONSTRAINT `fk_node_chunk` FOREIGN KEY (`source_chunk_id`) REFERENCES `courseware_chunk` (`id`) ON DELETE SET NULL ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='导图节点表';


-- ---------- 2. 薄弱知识点视图 ----------
-- 默认口径（与需求文档一致）：只看错题，按累计答错次数计分，封顶 100。
-- 说明：视图只做聚合，不落表；数据量增大后可改为定时物化表。
CREATE OR REPLACE VIEW `v_kp_weakness` AS
SELECT
    w.`user_id`                AS user_id,
    w.`knowledge_point_id`     AS knowledge_point_id,
    kp.`title`                 AS kp_title,
    kp.`chapter`               AS chapter,
    SUM(w.`wrong_count`)       AS wrong_total,
    ROUND(LEAST(100, SUM(w.`wrong_count`) * 10), 1) AS weakness_score,
    MAX(w.`last_wrong_at`)     AS last_activity_at
FROM `wrong_question` w
JOIN `knowledge_point` kp ON kp.`id` = w.`knowledge_point_id`
WHERE w.`knowledge_point_id` IS NOT NULL
  AND w.`status` <> 2
GROUP BY w.`user_id`, w.`knowledge_point_id`, kp.`title`, kp.`chapter`;

-- 扩展口径（A1 记忆卡片确认纳入后使用）：错题 ×8，卡片遗忘 ×4，封顶 100。
CREATE OR REPLACE VIEW `v_kp_weakness_ext` AS
SELECT
    t.user_id,
    t.knowledge_point_id,
    kp.`title`        AS kp_title,
    kp.`chapter`      AS chapter,
    SUM(t.wrong_cnt)  AS wrong_total,
    SUM(t.lapse_cnt)  AS lapse_total,
    ROUND(LEAST(100, SUM(t.wrong_cnt) * 8 + SUM(t.lapse_cnt) * 4), 1) AS weakness_score,
    MAX(t.last_at)    AS last_activity_at
FROM (
    SELECT `user_id`, `knowledge_point_id`,
           SUM(`wrong_count`) AS wrong_cnt, 0 AS lapse_cnt,
           MAX(`last_wrong_at`) AS last_at
    FROM `wrong_question`
    WHERE `knowledge_point_id` IS NOT NULL
      AND `status` <> 2
    GROUP BY `user_id`, `knowledge_point_id`
    UNION ALL
    SELECT `user_id`, `knowledge_point_id`,
           0 AS wrong_cnt, SUM(`lapses`) AS lapse_cnt,
           MAX(`last_reviewed_at`) AS last_at
    FROM `flashcard`
    WHERE `deleted_at` IS NULL
      AND `lapses` > 0
    GROUP BY `user_id`, `knowledge_point_id`
) t
JOIN `knowledge_point` kp ON kp.`id` = t.knowledge_point_id
GROUP BY t.`user_id`, t.`knowledge_point_id`, kp.`title`, kp.`chapter`;


-- ---------- 3. 卡片评分存储过程 ----------
-- 为什么放在一个事务里：评分要同时写 review_log（流水）和改 flashcard（状态），
-- 两个标签页同时评分时，FOR UPDATE 保证后到者拿到最新的 interval / EF。
-- 入参 next_interval / next_ease / due_at 由后端按 SM-2 算好传入，数据库只负责原子落库。
DROP PROCEDURE IF EXISTS `sp_review_card`;
DELIMITER $$
CREATE PROCEDURE `sp_review_card`(
    IN  p_card_id       BIGINT UNSIGNED,
    IN  p_user_id       BIGINT UNSIGNED,
    IN  p_rating        TINYINT,
    IN  p_next_interval INT UNSIGNED,
    IN  p_next_ease     DECIMAL(4,2),
    IN  p_due_at        DATETIME,
    IN  p_duration_ms   INT UNSIGNED,
    OUT p_code          INT
)
proc: BEGIN
    DECLARE v_prev_interval INT UNSIGNED DEFAULT NULL;
    DECLARE v_prev_ease     DECIMAL(4,2)  DEFAULT NULL;

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        SET p_code = -1;
    END;

    IF p_rating NOT BETWEEN 1 AND 4 THEN
        SET p_code = 400;          -- 评分越界
        LEAVE proc;
    END IF;

    START TRANSACTION;

    SELECT `interval_days`, `ease_factor`
      INTO v_prev_interval, v_prev_ease
      FROM `flashcard`
     WHERE `id` = p_card_id
       AND `user_id` = p_user_id
       AND `deleted_at` IS NULL
     FOR UPDATE;

    IF v_prev_ease IS NULL THEN
        ROLLBACK;
        SET p_code = 404;          -- 卡片不存在或不属于该用户
        LEAVE proc;
    END IF;

    INSERT INTO `review_log`
        (`card_id`, `user_id`, `rating`, `prev_interval_days`, `next_interval_days`,
         `prev_ease`, `next_ease`, `duration_ms`)
    VALUES
        (p_card_id, p_user_id, p_rating, v_prev_interval, p_next_interval,
         v_prev_ease, p_next_ease, p_duration_ms);

    UPDATE `flashcard`
       SET `interval_days`   = p_next_interval,
           `ease_factor`     = p_next_ease,
           `repetitions`     = IF(p_rating = 1, 0, `repetitions` + 1),
           `lapses`          = `lapses` + IF(p_rating = 1, 1, 0),
           `last_reviewed_at`= NOW(),
           `due_at`          = p_due_at,
           `state`           = IF(p_rating = 1, 1, 2)
     WHERE `id` = p_card_id;

    COMMIT;
    SET p_code = 0;
END proc$$
DELIMITER ;


-- ---------- 4. 种子数据（可直接跑通第 5 节全部查询） ----------
INSERT INTO `sys_user` (`id`, `username`, `password_hash`, `nickname`, `email`, `status`, `last_login_at`, `created_at`)
VALUES (1, 'wuyaqing', '$2b$12$KIXQ8g0Yq1mZ4pWc7dR2u.9xV6bN3sT5hJ8kL0mP4qR6sU8vW0xY2', '吴雅晴', 'wuyaqing@example.com', 1, '2026-11-05 13:14:00', '2026-09-12 02:00:00');

INSERT INTO `courseware` (`id`, `user_id`, `title`, `course_name`, `file_name`, `file_type`, `file_size`, `storage_path`, `page_count`, `parse_status`, `uploaded_at`)
VALUES (1, 1, 'Ch7 线性回归与逻辑回归', '机器学习', 'Ch7-线性回归与逻辑回归.pptx', 'pptx', 3571712, 'u/1/2026/11/ch7-linear.pptx', 42, 2, '2026-11-02 07:20:00');

INSERT INTO `courseware_chunk` (`id`, `courseware_id`, `page_no`, `chunk_index`, `content_type`, `content`, `latex`, `char_start`, `char_end`, `token_count`, `embedding_ref`)
VALUES
(1, 1, 5, 1, 1, '线性回归假设输出是输入特征的线性组合，模型形式为 y = w^T x + b。', NULL, 0, 38, 24, 'emb_0001'),
(2, 1, 5, 2, 2, 'y = w^T x + b', 'y = \\mathbf{w}^{\\top}\\mathbf{x} + b', 39, 55, 12, 'emb_0002'),
(3, 1, 6, 1, 1, '最小二乘法通过最小化残差平方和求解参数，解析解为 w = (X^T X)^{-1} X^T y。', NULL, 0, 43, 26, 'emb_0003'),
(4, 1, 7, 1, 3, '表 7-1 L1 与 L2 正则化的对比：L1 产生稀疏解，L2 使权重整体收缩。', NULL, 0, 37, 22, 'emb_0004'),
(5, 1, 12, 1, 1, '逻辑回归先用线性函数得到 z，再用 Sigmoid 把 z 映射到 (0,1)，输出正类概率。', NULL, 0, 42, 25, 'emb_0005'),
(6, 1, 12, 2, 2, 'sigma(z) = 1 / (1 + e^{-z})', '\\sigma(z)=\\frac{1}{1+e^{-z}}', 43, 72, 14, 'emb_0006'),
(7, 1, 15, 1, 1, '交叉熵损失衡量预测分布与真实标签的差异，二分类形式为 L = -[y log p + (1-y) log(1-p)]。', NULL, 0, 55, 30, 'emb_0007'),
(8, 1, 18, 1, 5, 'for epoch in range(n): w -= lr * grad', NULL, 0, 40, 18, 'emb_0008');

INSERT INTO `note` (`id`, `courseware_id`, `user_id`, `title`, `summary`, `status`, `version`, `created_at`, `updated_at`)
VALUES (1, 1, 1, '第7章 线性回归与逻辑回归 · 结构化笔记',
        '本章从线性回归的模型形式与最小二乘出发，介绍正则化，再过渡到逻辑回归、Sigmoid 与交叉熵损失，最后给出梯度下降的更新规则。',
        1, 1, '2026-11-02 07:26:00', '2026-11-02 07:26:00');

INSERT INTO `note_section` (`id`, `note_id`, `parent_id`, `heading`, `level`, `content_md`, `order_no`, `page_from`, `page_to`)
VALUES
(1, 1, NULL, '7.1 线性回归', 1, '线性回归用输入特征的线性组合拟合连续输出。', 1, 5, 7),
(3, 1, NULL, '7.2 逻辑回归', 1, '逻辑回归用 Sigmoid 把线性输出压缩到 (0,1)，输出正类概率。', 2, 12, 13),
(4, 1, NULL, '7.3 损失函数与优化', 1, '二分类交叉熵配合梯度下降更新参数。', 3, 15, 18);
INSERT INTO `note_section` (`id`, `note_id`, `parent_id`, `heading`, `level`, `content_md`, `order_no`, `page_from`, `page_to`)
VALUES (2, 1, 1, '7.1.1 最小二乘与正则化', 2, '最小二乘最小化残差平方和；L1/L2 正则化用于控制过拟合。', 1, 6, 7);

INSERT INTO `knowledge_point` (`id`, `courseware_id`, `note_id`, `source_chunk_id`, `kp_code`, `chapter`, `title`, `summary`, `difficulty`)
VALUES
(1, 1, 1, 1, 'KP-7-1-1', '第7章', '线性回归的模型形式', '输出是输入特征的线性组合：y = w^T x + b。', 2),
(2, 1, 1, 3, 'KP-7-1-2', '第7章', '最小二乘与正则化', '最小化残差平方和求解析解，L1/L2 控制过拟合。', 3),
(3, 1, 1, 5, 'KP-7-2-1', '第7章', '逻辑回归与 Sigmoid', 'Sigmoid 把线性输出映射到 (0,1)，值域为开区间。', 3),
(4, 1, 1, 7, 'KP-7-3-1', '第7章', '交叉熵损失', '二分类交叉熵 L = -[y log p + (1-y) log(1-p)]。', 4);

INSERT INTO `qa_record` (`id`, `user_id`, `courseware_id`, `question`, `answer`, `cited_chunk_ids`, `confidence`, `created_at`)
VALUES (1, 1, 1, '为什么逻辑回归用交叉熵而不是均方误差？',
        '交叉熵对应伯努利分布的最大似然，梯度中误差项被 Sigmoid 导数抵消，不会像均方误差那样在饱和区梯度消失；同时它是凸函数，优化更稳定。',
        '[7]', 0.860, '2026-11-05 12:30:00');

INSERT INTO `flashcard` (`id`, `user_id`, `knowledge_point_id`, `courseware_id`, `card_type`, `front`, `back`, `source_chunk_id`, `source_page`, `state`, `ease_factor`, `interval_days`, `repetitions`, `lapses`, `due_at`, `last_reviewed_at`, `origin`)
VALUES
(1, 1, 1, 1, 1, '线性回归的模型形式是什么？', 'y = w^T x + b，其中 w 为权重向量、b 为偏置。', 1, 5, 2, 2.35, 6, 2, 0, '2026-11-06 20:00:00', '2026-11-01 13:00:00', 1),
(2, 1, 1, 1, 2, '线性回归假设输出是输入特征的____组合。', '线性', 1, 5, 0, 2.50, 0, 0, 0, '2026-11-05 20:00:00', NULL, 1),
(3, 1, 3, 1, 1, 'Sigmoid 函数的值域是什么？', '(0,1)，即开区间，不含 0 和 1。', 5, 12, 2, 2.30, 3, 3, 1, '2026-11-05 20:00:00', '2026-10-28 12:10:00', 1),
(4, 1, 4, 1, 1, '二分类交叉熵的表达式是什么？', 'L = -[y log p + (1-y) log(1-p)]。', 7, 15, 1, 2.20, 1, 0, 1, '2026-11-05 20:00:00', '2026-11-04 11:10:00', 2);

INSERT INTO `review_log` (`id`, `card_id`, `user_id`, `rating`, `prev_interval_days`, `next_interval_days`, `prev_ease`, `next_ease`, `duration_ms`, `reviewed_at`)
VALUES
(1, 1, 1, 2, 0, 1, 2.50, 2.35, 8200, '2026-10-26 13:00:00'),
(2, 1, 1, 3, 1, 3, 2.35, 2.35, 6100, '2026-10-29 12:40:00'),
(3, 1, 1, 3, 3, 6, 2.35, 2.35, 5400, '2026-11-01 13:00:00'),
(4, 3, 1, 1, 6, 1, 2.50, 2.30, 12000, '2026-10-24 11:30:00'),
(5, 3, 1, 3, 1, 3, 2.30, 2.30, 7300, '2026-10-28 12:10:00'),
(6, 4, 1, 2, 0, 1, 2.35, 2.20, 15000, '2026-11-04 11:10:00');

INSERT INTO `wrong_question` (`id`, `user_id`, `knowledge_point_id`, `courseware_id`, `source_type`, `source_id`, `question_type`, `stem`, `user_answer`, `correct_answer`, `analysis`, `source_chunk_id`, `source_page`, `wrong_count`, `status`, `last_wrong_at`)
VALUES
(1, 1, 4, 1, 1, 1, 5, '逻辑回归的损失函数通常采用？', '均方误差', '交叉熵',
 '均方误差在 Sigmoid 饱和区梯度接近 0，且非凸；交叉熵对应最大似然，梯度更稳定。', 7, 15, 2, 0, '2026-11-05 12:30:00'),
(2, 1, 3, 1, 2, 2, 1, '关于 Sigmoid 函数，下列说法正确的是？', 'B', 'C',
 'Sigmoid 值域是 (0,1) 的开区间，且关于 (0, 0.5) 中心对称；它在两端饱和，导数趋近 0。', 5, 12, 1, 1, '2026-11-04 11:10:00'),
(3, 1, 4, 1, 2, 3, 3, '二分类交叉熵中，当预测概率 p 趋近 0 而真实标签 y=1 时，损失会____。', '趋于 0', '趋于无穷大',
 '此时 -log(p) 趋于正无穷，说明模型对正确类别的预测越不自信，惩罚越大。', 7, 15, 1, 0, '2026-11-04 11:10:00');

INSERT INTO `self_test` (`id`, `user_id`, `courseware_id`, `title`, `scope`, `question_types`, `question_count`, `total_score`, `score`, `correct_count`, `status`, `started_at`, `submitted_at`, `duration_sec`, `created_at`)
VALUES (1, 1, 1, '第7章 自测（3 题）', '{"chapter":"第7章","kp_ids":[1,3,4]}', '[1,3]', 3, 100.00, 33.33, 1, 3, '2026-11-04 10:50:00', '2026-11-04 11:10:00', 512, '2026-11-04 10:45:00');

INSERT INTO `self_test_item` (`id`, `test_id`, `seq_no`, `question_type`, `knowledge_point_id`, `stem`, `options`, `correct_answer`, `user_answer`, `is_correct`, `score`, `max_score`, `analysis`, `source_chunk_id`, `source_page`, `answered_at`)
VALUES
(1, 1, 1, 1, 1, '线性回归的解析解可以写成？', '["A. (X^T X)^{-1} X^T y", "B. X^T y", "C. (X X^T)^{-1} y", "D. X^{-1} y"]', 'A', 'A', 1, 33.33, 33.33,
 '最小二乘目标对 w 求导并令其为 0，得到正规方程 X^T X w = X^T y。', 3, 6, '2026-11-04 10:58:00'),
(2, 1, 2, 1, 3, '关于 Sigmoid 函数，下列说法正确的是？', '["A. 值域为 [0,1]", "B. 值域为 (-1,1)", "C. 值域为 (0,1) 且两端饱和", "D. 单调递减"]', 'C', 'B', 0, 0.00, 33.33,
 'Sigmoid 值域是开区间 (0,1)，单调递增，两端导数趋近 0。', 5, 12, '2026-11-04 11:02:00'),
(3, 1, 3, 3, 4, '二分类交叉熵中，当预测概率 p 趋近 0 而真实标签 y=1 时，损失会____。', NULL, '趋于无穷大', '趋于 0', 0, 0.00, 33.34,
 '此时 -log(p) 趋于正无穷，模型受到很大惩罚。', 7, 15, '2026-11-04 11:08:00');

-- 种子里的错题已由第 2、3 题回填，标记为已回填，避免重复计数
UPDATE `self_test_item` SET `is_backfilled` = 1 WHERE `is_correct` = 0;

INSERT INTO `mindmap_node` (`id`, `courseware_id`, `user_id`, `parent_id`, `title`, `node_type`, `knowledge_point_id`, `summary`, `source_chunk_id`, `page_no`, `level`, `order_no`, `is_collapsed`)
VALUES (1, 1, 1, NULL, '第7章 线性回归与逻辑回归', 1, NULL, '本章知识结构总览', NULL, NULL, 1, 1, 0);
INSERT INTO `mindmap_node` (`id`, `courseware_id`, `user_id`, `parent_id`, `title`, `node_type`, `knowledge_point_id`, `summary`, `source_chunk_id`, `page_no`, `level`, `order_no`, `is_collapsed`)
VALUES
(2, 1, 1, 1, '线性回归', 2, NULL, '用线性组合拟合连续输出', 1, 5, 2, 1, 0),
(5, 1, 1, 1, '逻辑回归', 2, NULL, '用 Sigmoid 输出正类概率', 5, 12, 2, 2, 0);
INSERT INTO `mindmap_node` (`id`, `courseware_id`, `user_id`, `parent_id`, `title`, `node_type`, `knowledge_point_id`, `summary`, `source_chunk_id`, `page_no`, `level`, `order_no`, `is_collapsed`)
VALUES
(3, 1, 1, 2, '模型形式', 4, 1, 'y = w^T x + b', 1, 5, 3, 1, 0),
(4, 1, 1, 2, '最小二乘与正则化', 4, 2, '残差平方和最小化，L1/L2 控制过拟合', 3, 6, 3, 2, 0),
(6, 1, 1, 5, 'Sigmoid 函数', 4, 3, '把 z 映射到 (0,1)', 5, 12, 3, 1, 0),
(7, 1, 1, 5, '交叉熵损失', 4, 4, 'L = -[y log p + (1-y) log(1-p)]', 7, 15, 3, 2, 0);


-- ---------- 5. 验收查询 ----------
-- Q1 今日待复习（含知识点与出处，走 idx_user_due）
-- 边界 ? 由服务层按 Asia/Shanghai 的“次日 04:00”换算成 UTC 后传入，不依赖会话时区
SELECT f.`id`, f.`card_type`, f.`front`, f.`due_at`,
       kp.`title` AS kp_title, c.`page_no`, c.`chunk_index`
FROM `flashcard` f
JOIN `knowledge_point` kp ON kp.`id` = f.`knowledge_point_id`
LEFT JOIN `courseware_chunk` c ON c.`id` = f.`source_chunk_id`
WHERE f.`user_id` = 1
  AND f.`deleted_at` IS NULL
  AND f.`state` IN (0, 1, 2)
  AND f.`due_at` < ?
ORDER BY f.`due_at`
LIMIT 50;

-- Q2 薄弱知识点 TOP10（默认口径：只看错题；A1 确认后改用 v_kp_weakness_ext）
SELECT `kp_title`, `chapter`, `wrong_total`, `lapse_total`, `weakness_score`
FROM `v_kp_weakness`
WHERE `user_id` = 1
ORDER BY `weakness_score` DESC, `wrong_total` DESC
LIMIT 10;

-- Q3 错题本：按章节、状态筛选（走 idx_user_status）
SELECT w.`id`, kp.`chapter`, kp.`title` AS kp_title,
       w.`stem`, w.`wrong_count`, w.`status`, w.`last_wrong_at`
FROM `wrong_question` w
LEFT JOIN `knowledge_point` kp ON kp.`id` = w.`knowledge_point_id`
WHERE w.`user_id` = 1
  AND w.`status` = 0
  AND kp.`chapter` = '第7章'
ORDER BY w.`last_wrong_at` DESC
LIMIT 20;

-- Q4 一次拉出整张导图（MySQL 8 递归 CTE，按路径排序）
WITH RECURSIVE `tree` AS (
    SELECT `id`, `parent_id`, `title`, `node_type`, `knowledge_point_id`,
           `level`, `order_no`, 1 AS `depth`,
           CAST(LPAD(`order_no`, 4, '0') AS CHAR(500)) AS `path`
    FROM `mindmap_node`
    WHERE `courseware_id` = 1 AND `parent_id` IS NULL
    UNION ALL
    SELECT n.`id`, n.`parent_id`, n.`title`, n.`node_type`, n.`knowledge_point_id`,
           n.`level`, n.`order_no`, t.`depth` + 1,
           CONCAT(t.`path`, '/', LPAD(n.`order_no`, 4, '0'))
    FROM `mindmap_node` n
    JOIN `tree` t ON n.`parent_id` = t.`id`
    WHERE t.`depth` < 6
)
SELECT `depth`, `title`, `node_type`, `knowledge_point_id`, `path`
FROM `tree`
ORDER BY `path`;

-- Q5 从知识点幂等生成问答卡（唯一键 uk_user_kp_type 保证重复执行不新增）
INSERT IGNORE INTO `flashcard`
    (`user_id`, `knowledge_point_id`, `courseware_id`, `card_type`,
     `front`, `back`, `source_chunk_id`, `source_page`, `origin`)
SELECT cw.`user_id`, kp.`id`, kp.`courseware_id`, 1,
       CONCAT('请简述：', kp.`title`), kp.`summary`,
       kp.`source_chunk_id`, c.`page_no`, 1
FROM `knowledge_point` kp
JOIN `courseware` cw ON cw.`id` = kp.`courseware_id`
LEFT JOIN `courseware_chunk` c ON c.`id` = kp.`source_chunk_id`
WHERE kp.`courseware_id` = 1
  AND kp.`summary` IS NOT NULL;
SELECT ROW_COUNT() AS `新增卡片数`;

-- Q6 交卷批改事务（后端按题循环执行，此处以第 2 题为例）
START TRANSACTION;
UPDATE `self_test_item`
   SET `user_answer` = 'B', `is_correct` = 0, `score` = 0, `answered_at` = NOW()
 WHERE `id` = 2 AND `test_id` = 1 AND `user_answer` IS NULL;

INSERT INTO `wrong_question`
    (`user_id`, `knowledge_point_id`, `courseware_id`, `source_type`, `source_id`,
     `question_type`, `stem`, `user_answer`, `correct_answer`, `analysis`,
     `source_chunk_id`, `source_page`, `wrong_count`, `status`, `last_wrong_at`)
SELECT t.`user_id`, i.`knowledge_point_id`, t.`courseware_id`, 2, i.`id`,
       i.`question_type`, i.`stem`, i.`user_answer`, i.`correct_answer`, i.`analysis`,
       i.`source_chunk_id`, i.`source_page`, 1, 0, NOW()
FROM `self_test_item` i
JOIN `self_test` t ON t.`id` = i.`test_id`
 WHERE i.`id` = 2 AND i.`is_correct` = 0 AND i.`is_backfilled` = 0
ON DUPLICATE KEY UPDATE `wrong_question`.`wrong_count` = `wrong_question`.`wrong_count` + 1,
                        `wrong_question`.`last_wrong_at` = NOW(),
                        `wrong_question`.`status` = 0;

-- 标记已回填：重复交卷时上面的 SELECT 选不到该题，不会二次累加
UPDATE `self_test_item`
   SET `is_backfilled` = 1
 WHERE `test_id` = 1 AND `is_correct` = 0 AND `is_backfilled` = 0;

UPDATE `self_test` t
   SET t.`score` = (SELECT COALESCE(SUM(`score`), 0) FROM `self_test_item` WHERE `test_id` = t.`id`),
       t.`correct_count` = (SELECT COUNT(*) FROM `self_test_item` WHERE `test_id` = t.`id` AND `is_correct` = 1),
       t.`status` = 3,
       t.`submitted_at` = NOW()
 WHERE t.`id` = 1 AND t.`status` = 2;
COMMIT;

-- Q7 一致性巡检：孤儿卡片应为 0 行
SELECT f.`id`, f.`knowledge_point_id`
FROM `flashcard` f
LEFT JOIN `knowledge_point` kp ON kp.`id` = f.`knowledge_point_id`
WHERE f.`deleted_at` IS NULL AND kp.`id` IS NULL;

-- Q8 一致性巡检：SM-2 参数越界应为 0 行
SELECT `id`, `ease_factor`, `interval_days`
FROM `flashcard`
WHERE `ease_factor` < 1.30 OR `ease_factor` > 5.00;

-- Q10 版本一致性巡检：卡片/错题/自测题/导图的版本应与知识点一致，应为 0 行
SELECT 'flashcard' AS `src`, f.`id`, f.`note_version` AS `ver`, kp.`note_version` AS `kp_ver`
FROM `flashcard` f
JOIN `knowledge_point` kp ON kp.`id` = f.`knowledge_point_id`
WHERE f.`note_version` <> kp.`note_version`
UNION ALL
SELECT 'wrong_question', w.`id`, w.`note_version`, kp.`note_version`
FROM `wrong_question` w
JOIN `knowledge_point` kp ON kp.`id` = w.`knowledge_point_id`
WHERE w.`knowledge_point_id` IS NOT NULL AND w.`note_version` <> kp.`note_version`
UNION ALL
SELECT 'self_test_item', i.`id`, i.`note_version`, kp.`note_version`
FROM `self_test_item` i
JOIN `knowledge_point` kp ON kp.`id` = i.`knowledge_point_id`
WHERE i.`knowledge_point_id` IS NOT NULL AND i.`note_version` <> kp.`note_version`
UNION ALL
SELECT 'mindmap_node', n.`id`, n.`note_version`, kp.`note_version`
FROM `mindmap_node` n
JOIN `knowledge_point` kp ON kp.`id` = n.`knowledge_point_id`
WHERE n.`knowledge_point_id` IS NOT NULL AND n.`note_version` <> kp.`note_version`;

-- Q9 原文块被知识点引用率（衡量笔记抽取质量）
SELECT cw.`title`,
       COUNT(DISTINCT c.`id`) AS `chunk_cnt`,
       COUNT(DISTINCT kp.`source_chunk_id`) AS `cited_chunk_cnt`,
       ROUND(COUNT(DISTINCT kp.`source_chunk_id`) / COUNT(DISTINCT c.`id`) * 100, 1) AS `coverage_pct`
FROM `courseware` cw
LEFT JOIN `courseware_chunk` c ON c.`courseware_id` = cw.`id`
LEFT JOIN `knowledge_point` kp ON kp.`courseware_id` = cw.`id`
WHERE cw.`id` = 1
GROUP BY cw.`id`, cw.`title`;


-- ---------- 6. 增量迁移（已有库升级时执行，勿与建表段重复） ----------
-- 6.1 课件原文块补充理工科课件需要的公式、图注、字符区间与向量引用
-- ALTER TABLE `courseware_chunk`
--     ADD COLUMN `content_type`  TINYINT     NOT NULL DEFAULT 1 COMMENT '1 文本 2 公式 3 表格 4 图注 5 代码' AFTER `chunk_index`,
--     ADD COLUMN `latex`         TEXT        NULL COMMENT '公式 LaTeX 源码' AFTER `content`,
--     ADD COLUMN `image_path`    VARCHAR(500) NULL COMMENT '图注/表格截图路径' AFTER `latex`,
--     ADD COLUMN `char_start`    INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '页内起始偏移' AFTER `content`,
--     ADD COLUMN `char_end`      INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '页内结束偏移' AFTER `char_start`,
--     ADD COLUMN `embedding_ref` VARCHAR(100) NULL COMMENT '向量库主键' AFTER `token_count`,
--     ADD FULLTEXT KEY `ft_chunk_content` (`content`) WITH PARSER ngram;

-- 6.2 版本绑定与回填标记（V1.1 新增）
-- ALTER TABLE `knowledge_point`
--     ADD COLUMN `note_version` INT UNSIGNED NOT NULL DEFAULT 1 COMMENT '所属笔记版本' AFTER `note_id`,
--     DROP INDEX `uk_course_kpcode`,
--     ADD UNIQUE KEY `uk_course_kpcode` (`courseware_id`, `note_version`, `kp_code`);
-- ALTER TABLE `flashcard`
--     ADD COLUMN `note_version` INT UNSIGNED NOT NULL DEFAULT 1 COMMENT '建卡时的笔记版本' AFTER `courseware_id`;
-- ALTER TABLE `wrong_question`
--     ADD COLUMN `note_version` INT UNSIGNED NOT NULL DEFAULT 1 COMMENT '收录时的笔记版本' AFTER `courseware_id`;
-- ALTER TABLE `self_test_item`
--     ADD COLUMN `note_version` INT UNSIGNED NOT NULL DEFAULT 1 COMMENT '组卷时的笔记版本' AFTER `knowledge_point_id`,
--     ADD COLUMN `is_backfilled` TINYINT NOT NULL DEFAULT 0 COMMENT '错题是否已回填' AFTER `is_correct`;
-- ALTER TABLE `mindmap_node`
--     ADD COLUMN `note_version` INT UNSIGNED NOT NULL DEFAULT 1 COMMENT '导图生成时的笔记版本' AFTER `courseware_id`;

-- 6.3 其余 6 张新表直接执行第 1 节中对应 CREATE TABLE 语句；
-- 6.4 上线顺序：建表 → 建视图 → 建存储过程 → 回填 note_version → 回填 knowledge_point.source_chunk_id。
