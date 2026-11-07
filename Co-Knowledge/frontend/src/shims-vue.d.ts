// eslint-disable-next-line no-unused-vars
import { App } from 'vue';

declare module 'vue' {
  // eslint-disable-next-line no-unused-vars
  interface ComponentCustomProperties {}
}
declare module '*.vue' {
  // eslint-disable-next-line no-duplicate-imports
  import Vue from 'vue';
  export default Vue;
}
