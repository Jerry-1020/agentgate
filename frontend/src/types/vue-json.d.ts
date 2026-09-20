import type { JsonObject } from '../views/datasets/types/index';

// API JSON values cannot contain Vue refs. Do not recursively unwrap their
// unbounded schema: Vue 3.4 / TypeScript 5.3 otherwise exceed instantiation depth.
declare module '@vue/reactivity' {
  interface RefUnwrapBailTypes {
    apiJson: JsonObject;
  }
}
