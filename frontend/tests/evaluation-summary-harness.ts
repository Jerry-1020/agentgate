import { mount } from '@vue/test-utils';
import { h } from 'vue';
import * as Vue from 'vue';
import { compile } from '@vue/compiler-dom';
import { createRouter, createMemoryHistory, RouterView } from 'vue-router';
import ElementPlus from 'element-plus';
import { pinia } from '../src/stores';
import { useAuthStore } from '../src/stores/modules/auth';
import Parent from '../src/views/evaluation/index.vue';
import TaskList from '../src/views/evaluation/components/TaskList.vue';
import OverviewMetrics from '../src/views/evaluation/components/OverviewMetrics.vue';
import * as helpers from '../src/views/evaluation/utils/summary-query';
const auth = useAuthStore(pinia);
auth.loginExternal();
let wrapper: ReturnType<typeof mount>;
let router: ReturnType<typeof createRouter>;
const simple = (name: string) => ({ template: `<div>${name}</div>` });
const dirty = (name: string) => ({ template: `<section>${name}<button @click="$emit('dirty-change', true)">dirty</button><button @click="$emit('run-version', {id:'dataset',version:1})">dataset launch</button><button @click="$emit('launch','judge')">judge launch</button></section>` });
const form = { template: `<section>Task form<button @click="$emit('created',{id:'created',kind:'single',runIds:['created-run'],staticReports:[]})">submit single</button><button @click="$emit('created',{id:'stable',kind:'stability',runIds:['s'],staticReports:[]})">submit stability</button><button @click="$emit('close')">close form</button></section>` };
const detail = { props: ['id','taskId'], template: `<section>Detail {{id}} {{taskId}}<button @click="$emit('rerun-created', taskId)">detail rerun complete</button><button @click="$emit('navigate', 'tasks')">detail back</button></section>` };
const rerun = { props: ['id','taskId'], template: `<section>Rerun {{id}} {{taskId}}<button @click="$emit('created',taskId || 'created')">rerun complete</button><button @click="$emit('close')">close rerun</button></section>` };
const layout = { props: ['hideAuthControls'], template: `<main><button v-if="!hideAuthControls" @click="$emit('logout')">logout</button><slot/><slot name="dialogs"/></main>` };
(window as any).summaryHarness = {
  helpers,
  auth: (values: object) => auth.$patch(values),
  async mount(path='/tasks', component='parent', props={}) {
    wrapper?.unmount();
    if (component !== 'parent') {
      wrapper = mount(component === 'list' ? TaskList : OverviewMetrics, { attachTo: '#app', props,
        global: { plugins: [pinia, ElementPlus] } });
      return;
    }
    router=createRouter({history:createMemoryHistory(), routes:[{path:'/:pathMatch(.*)*',component:Parent}]});
    await router.push(path); await router.isReady();
    wrapper=mount({render:()=>h(RouterView)}, {attachTo:'#app', global:{plugins:[pinia,ElementPlus,router],stubs:Object.fromEntries(Object.entries({
      EvaluationLayout:layout, EvaluationTaskForm:form, RunDetail:detail, RerunDialog:rerun,
      DatasetWorkspace:dirty('Datasets'), JudgeSystem:dirty('Judges'), ModelSettings:dirty('Settings'),
      ScoringTemplates:dirty('Scoring'), Stability:simple('Stability'), Comparisons:simple('Comparisons'),
      TaskStaticAnalysis:simple('Static'), TaskTuning:simple('Tuning'), Analysis:simple('Analysis'),
    }).map(([name, component]) => [name, { ...component, render: new Function('Vue', compile(component.template).code)(Vue) }]))}});
  },
  navigate: (path: string) => router.push(path),
  unmount: () => wrapper.unmount(),
  props: (value: object) => wrapper.setProps(value),
  events: () => wrapper.emitted(),
};
