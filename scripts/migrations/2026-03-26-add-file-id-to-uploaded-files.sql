-- 为 uploaded_files 表添加 file_id 列
ALTER TABLE uploaded_files ADD COLUMN IF NOT EXISTS file_id VARCHAR(64);
