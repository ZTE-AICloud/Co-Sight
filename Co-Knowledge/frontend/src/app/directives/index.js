import { vTooltip } from './tooltip/src/index.ts';
import trim from './trim/index.js';

export default {
  install (Vue) {
    Vue.directive('tooltip', vTooltip);
    Vue.use(trim);
  }
};
