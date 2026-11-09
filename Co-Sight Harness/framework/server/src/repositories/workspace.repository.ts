/**
 * 工作区仓储（需求 2.1；语义见 D16 = A）。
 *
 * 工作区名唯一由应用层保证而非唯一索引：这样能返回带 i18n 键的 CONFLICT 错误，
 * 而不是把 SQLITE_CONSTRAINT 这种驱动级报错透给用户。本地单用户场景没有
 * 并发建同名的现实风险。
 */

import { asc, eq } from 'drizzle-orm';

import type { CreateWorkspaceInput, UpdateWorkspaceInput, Workspace } from 'harness-shared';

import type { Database } from '../db/client';
import { workspaces, type WorkspaceRow } from '../db/schema';
import { newId } from '../lib/id';

function toWorkspace(row: WorkspaceRow): Workspace {
  return {
    id: row.id,
    name: row.name,
    directory: row.directory,
    defaultModelId: row.defaultModelId,
    defaultAgentId: row.defaultAgentId,
    createdAt: row.createdAt.toISOString(),
    updatedAt: row.updatedAt.toISOString(),
  };
}

export class WorkspaceRepository {
  readonly #db: Database;

  constructor(db: Database) {
    this.#db = db;
  }

  async list(): Promise<Workspace[]> {
    const rows = await this.#db
      .select()
      .from(workspaces)
      .orderBy(asc(workspaces.createdAt), asc(workspaces.id));
    return rows.map(toWorkspace);
  }

  async findById(id: string): Promise<Workspace | null> {
    const [row] = await this.#db.select().from(workspaces).where(eq(workspaces.id, id)).limit(1);
    return row === undefined ? null : toWorkspace(row);
  }

  async findByName(name: string): Promise<Workspace | null> {
    const [row] = await this.#db.select().from(workspaces).where(eq(workspaces.name, name)).limit(1);
    return row === undefined ? null : toWorkspace(row);
  }

  async create(input: CreateWorkspaceInput, now: Date = new Date()): Promise<Workspace> {
    const row: WorkspaceRow = {
      id: newId(),
      name: input.name,
      directory: input.directory,
      defaultModelId: input.defaultModelId,
      defaultAgentId: input.defaultAgentId,
      createdAt: now,
      updatedAt: now,
    };
    await this.#db.insert(workspaces).values(row);
    return toWorkspace(row);
  }

  /** 部分更新。返回 null 表示工作区不存在。 */
  async update(
    id: string,
    patch: UpdateWorkspaceInput,
    now: Date = new Date(),
  ): Promise<Workspace | null> {
    // 只把"确实提供了"的字段写进去：`undefined` 是"不改"，
    // `null` 是"显式清空"（如解绑目录）。两者语义不同，不能合并。
    const changes: Partial<WorkspaceRow> = { updatedAt: now };
    if (patch.name !== undefined) {
      changes.name = patch.name;
    }
    if (patch.directory !== undefined) {
      changes.directory = patch.directory;
    }
    if (patch.defaultModelId !== undefined) {
      changes.defaultModelId = patch.defaultModelId;
    }
    if (patch.defaultAgentId !== undefined) {
      changes.defaultAgentId = patch.defaultAgentId;
    }

    const rows = await this.#db
      .update(workspaces)
      .set(changes)
      .where(eq(workspaces.id, id))
      .returning();
    const [row] = rows;
    return row === undefined ? null : toWorkspace(row);
  }

  async deleteById(id: string): Promise<boolean> {
    const rows = await this.#db.delete(workspaces).where(eq(workspaces.id, id)).returning({
      id: workspaces.id,
    });
    return rows.length > 0;
  }
}
