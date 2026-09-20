// Compatibility entry for existing views; shared state is owned by Pinia.
import { storeToRefs } from 'pinia';
import { pinia } from './index';
import { useReviewStore } from './modules/review';
export type {
  Criterion,
  ScoringTemplate,
  AnnotationTemplate,
  AnnotationTask,
  JudgeDraft,
} from './modules/review';
export { copy } from './modules/review';
const review = useReviewStore(pinia);
export const {
  scoringDrafts,
  annotationTemplates,
  annotationStorageError,
  annotationTasks,
  judgeDrafts,
  evaluatorCatalog,
  evaluatorDetails,
  extractedTemplates,
  assetsError,
  assetsLoading,
} = storeToRefs(review);
export const { ensureAnnotationExample, loadReviewAssets, validateCriteria, exportUx } = review;
