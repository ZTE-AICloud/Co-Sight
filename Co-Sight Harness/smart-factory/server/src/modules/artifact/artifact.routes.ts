import { Router } from 'express';
import { artifactController } from './artifact.controller.js';

/** 挂载点：/api/smart-factory/v1（artifacts/*） */
export const artifactRouter = Router();

artifactRouter.get('/artifacts/list', artifactController.list);
artifactRouter.get('/artifacts/file', artifactController.file);
artifactRouter.get('/artifacts/download', artifactController.download);
