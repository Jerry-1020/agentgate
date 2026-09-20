import { pinia } from '../../../stores';
import { useTaskLinksStore } from '../../../stores/modules/task-links';
export type { TaskLink } from '../../../stores/modules/task-links';
export const { readTaskLinks, refreshTaskLinks, saveTaskLink } = useTaskLinksStore(pinia);
