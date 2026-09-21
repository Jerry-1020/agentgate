<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, watch } from 'vue';
import { EditorState, Compartment } from '@codemirror/state';
import { EditorView, basicSetup } from 'codemirror';
import { json } from '@codemirror/lang-json';
const props = defineProps<{ modelValue: string; disabled?: boolean; label: string }>();
const emit = defineEmits<{ 'update:modelValue': [value: string] }>();
const container = ref<HTMLDivElement>(),
  editable = new Compartment();
let view: EditorView | undefined;
onMounted(() => {
  view = new EditorView({
    parent: container.value,
    state: EditorState.create({
      doc: props.modelValue,
      extensions: [
        basicSetup,
        json(),
        EditorView.lineWrapping,
        EditorView.contentAttributes.of({
          'aria-label': props.label,
          role: 'textbox',
          'aria-multiline': 'true',
        }),
        editable.of([
          EditorState.readOnly.of(!!props.disabled),
          EditorView.editable.of(!props.disabled),
        ]),
        EditorView.updateListener.of((update) => {
          if (update.docChanged) emit('update:modelValue', update.state.doc.toString());
        }),
        EditorView.theme({
          '&': { fontSize: '13px' },
          '.cm-scroller': { maxHeight: '320px', minHeight: '140px', overflow: 'auto' },
          '.cm-gutters': { backgroundColor: '#f4f8f7' },
          '&.cm-focused': { outline: '2px solid #0aae92' },
        }),
      ],
    }),
  });
});
watch(
  () => props.modelValue,
  (value) => {
    if (view && value !== view.state.doc.toString())
      view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: value } });
  },
);
watch(
  () => props.disabled,
  (value) =>
    view?.dispatch({
      effects: editable.reconfigure([
        EditorState.readOnly.of(!!value),
        EditorView.editable.of(!value),
      ]),
    }),
);
onBeforeUnmount(() => view?.destroy());
</script>
<template><div ref="container" class="json-code-editor" /></template>
<style scoped>
.json-code-editor {
  margin-top: 8px;
  border: 1px solid #dbe2ee;
  border-radius: 7px;
  overflow: hidden;
}
</style>
