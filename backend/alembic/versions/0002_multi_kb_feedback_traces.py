"""multi knowledge base + feedback + query traces

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-16 15:00:00.000000

新增三张表（知识库 / 回答反馈 / 调用追踪），documents 挂知识库、
chat_sessions 记录会话知识库快照。chunks_fts 稀疏索引表补 knowledge_base
过滤列：PG 实体表可 ALTER，SQLite FTS5 虚表不支持 ALTER，只能 drop 重建
（dev/seed/eval 反正重灌，空表无妨；重建后由下次文档处理回填）。
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: str | Sequence[str] | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. 新表：知识库
    op.create_table('knowledge_bases',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('department', sa.String(length=64), nullable=False),
    sa.Column('description', sa.String(length=255), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('department', 'name', name='uq_kb_department_name')
    )
    op.create_index(op.f('ix_knowledge_bases_department'), 'knowledge_bases', ['department'], unique=False)

    # 2. 新表：回答反馈
    op.create_table('answer_feedback',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('message_id', sa.Integer(), nullable=False),
    sa.Column('sentiment', sa.String(length=16), nullable=False),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['message_id'], ['chat_messages.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'message_id', name='uq_feedback_user_message')
    )
    op.create_index(op.f('ix_answer_feedback_created_at'), 'answer_feedback', ['created_at'], unique=False)
    op.create_index(op.f('ix_answer_feedback_message_id'), 'answer_feedback', ['message_id'], unique=False)
    op.create_index(op.f('ix_answer_feedback_user_id'), 'answer_feedback', ['user_id'], unique=False)

    # 3. 新表：调用追踪
    op.create_table('query_traces',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('request_id', sa.String(length=64), nullable=True),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('department', sa.String(length=64), nullable=True),
    sa.Column('knowledge_base', sa.String(length=64), nullable=True),
    sa.Column('question', sa.Text(), nullable=False),
    sa.Column('rewritten_query', sa.Text(), nullable=True),
    sa.Column('cache_hit', sa.Boolean(), nullable=False),
    sa.Column('retrieved_count', sa.Integer(), nullable=False),
    sa.Column('no_answer', sa.Boolean(), nullable=False),
    sa.Column('llm_input_tokens', sa.Integer(), nullable=True),
    sa.Column('llm_output_tokens', sa.Integer(), nullable=True),
    sa.Column('latency_ms', sa.Integer(), nullable=False),
    sa.Column('stage_timing', sa.Text(), nullable=True),
    sa.Column('answer_preview', sa.String(length=512), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_query_traces_created_at'), 'query_traces', ['created_at'], unique=False)
    op.create_index(op.f('ix_query_traces_request_id'), 'query_traces', ['request_id'], unique=False)
    op.create_index(op.f('ix_query_traces_user_id'), 'query_traces', ['user_id'], unique=False)

    # 4. documents 挂知识库（nullable 兼容老数据，backfill 填默认库）
    if op.get_bind().dialect.name == "postgresql":
        op.add_column('documents', sa.Column('knowledge_base_id', sa.Integer(), nullable=True))
        op.create_index(op.f('ix_documents_knowledge_base_id'), 'documents', ['knowledge_base_id'], unique=False)
        op.create_foreign_key('fk_documents_knowledge_base', 'documents', 'knowledge_bases', ['knowledge_base_id'], ['id'])
    else:
        # SQLite 不支持 ALTER 加约束，用 batch 重建表（copy-and-move，保留数据）
        with op.batch_alter_table('documents') as batch_op:
            batch_op.add_column(sa.Column('knowledge_base_id', sa.Integer(), nullable=True))
            batch_op.create_index('ix_documents_knowledge_base_id', ['knowledge_base_id'], unique=False)
            batch_op.create_foreign_key('fk_documents_knowledge_base', 'knowledge_bases', ['knowledge_base_id'], ['id'])

    # 5. chat_sessions 记录会话知识库快照
    op.add_column('chat_sessions', sa.Column('knowledge_base', sa.String(length=64), nullable=True))

    # 6. chunks_fts 补 knowledge_base 过滤列（方言分支）
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "ALTER TABLE chunks_fts "
            "ADD COLUMN IF NOT EXISTS knowledge_base TEXT NOT NULL DEFAULT ''"
        )
    elif bind.dialect.name == "sqlite":
        # FTS5 虚表不支持 ALTER ADD COLUMN：drop 重建（空表，由文档处理回填）
        op.execute("DROP TABLE IF EXISTS chunks_fts")
        op.execute(
            "CREATE VIRTUAL TABLE chunks_fts USING fts5("
            "chunk_id UNINDEXED, department UNINDEXED, knowledge_base UNINDEXED, "
            "tokens, tokenize='unicode61')"
        )

    # 7. backfill：为 documents 里已有的每个部门建「默认知识库」，文档归入
    op.execute(
        "INSERT INTO knowledge_bases (name, department, description, is_active, created_at, updated_at) "
        "SELECT '默认知识库', department, '系统自动创建', TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
        "FROM documents GROUP BY department"
    )
    op.execute(
        "UPDATE documents SET knowledge_base_id = ("
        "SELECT id FROM knowledge_bases kb "
        "WHERE kb.department = documents.department AND kb.name = '默认知识库')"
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    # chunks_fts 回退为三列（SQLite 重建，PG ALTER）
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE chunks_fts DROP COLUMN IF EXISTS knowledge_base")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TABLE IF EXISTS chunks_fts")
        op.execute(
            "CREATE VIRTUAL TABLE chunks_fts USING fts5("
            "chunk_id UNINDEXED, department UNINDEXED, tokens, tokenize='unicode61')"
        )

    op.drop_column('chat_sessions', 'knowledge_base')
    if op.get_bind().dialect.name == "postgresql":
        op.drop_constraint('fk_documents_knowledge_base', 'documents', type_='foreignkey')
        op.drop_index(op.f('ix_documents_knowledge_base_id'), table_name='documents')
        op.drop_column('documents', 'knowledge_base_id')
    else:
        with op.batch_alter_table('documents') as batch_op:
            batch_op.drop_index('ix_documents_knowledge_base_id')
            batch_op.drop_column('knowledge_base_id')
    op.drop_index(op.f('ix_query_traces_user_id'), table_name='query_traces')
    op.drop_index(op.f('ix_query_traces_request_id'), table_name='query_traces')
    op.drop_index(op.f('ix_query_traces_created_at'), table_name='query_traces')
    op.drop_table('query_traces')
    op.drop_index(op.f('ix_answer_feedback_user_id'), table_name='answer_feedback')
    op.drop_index(op.f('ix_answer_feedback_message_id'), table_name='answer_feedback')
    op.drop_index(op.f('ix_answer_feedback_created_at'), table_name='answer_feedback')
    op.drop_table('answer_feedback')
    op.drop_index(op.f('ix_knowledge_bases_department'), table_name='knowledge_bases')
    op.drop_table('knowledge_bases')
    # ### end Alembic commands ###
