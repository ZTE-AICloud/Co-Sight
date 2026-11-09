import { Router } from 'express';
import { skillController } from './skill.controller.js';

/** 挂载点：/api/smart-factory/v1（skills） */
export const skillRouter = Router();

skillRouter.get('/skills', skillController.list);
