<script setup lang="ts">
import { ref, computed } from 'vue';
import { pretty } from '../../../api/evaluations';
const props = defineProps<{ kind: string }>();
const rule = ref(100),
  judge = ref(80),
  weight = ref(40),
  blocked = ref(false),
  decision = ref('未复核');
const total = computed(
  () => (rule.value * weight.value) / 100 + (judge.value * (100 - weight.value)) / 100,
);
</script>
<template>
  <section class="card section-gap">
    <h2 class="section-title">
      {{
        kind === 'static'
          ? '静态分析交互样例'
          : kind === 'hybrid'
            ? '复合评分计算样例'
            : 'LLM 评分输出样例'
      }}
    </h2>
    <span class="mock-label">Mock 演示 · 不参与真实测评</span>
    <template v-if="kind === 'static'">
      <div class="grid two-columns">
        <article>
          <h3>Skill A · 订单查询</h3>
          <p>查询订单状态及退款状态。</p>
        </article>
        <article>
          <h3>Skill B · 退款查询</h3>
          <p>查询退款进度及退款状态。</p>
        </article>
      </div>
      <h3>描述重叠：退款状态查询</h3>
      <p>
        两个 Skill
        都声明可以处理“退款到哪里了”，存在路由歧义。此发现是描述层风险，不等于运行时已经路由错误。
      </p>
      <p>
        建议：明确由退款查询处理退款进度，订单查询仅负责订单状态。修改资产后发布新版本，再用相应样本做动态测评验证。
      </p>
      <label class="field"
        >样例复核状态（仅本页）<select class="input" v-model="decision">
          <option>未复核</option>
          <option>已确认</option>
          <option>已排除</option>
        </select></label
      >
    </template>
    <template v-else-if="kind === 'hybrid'">
      <div class="form-grid">
        <label class="field"
          >规则分数（0—100）<input
            class="input"
            type="number"
            min="0"
            max="100"
            v-model.number="rule" /></label
        ><label class="field"
          >模型分数（0—100，假设值）<input
            class="input"
            type="number"
            min="0"
            max="100"
            v-model.number="judge" /></label
        ><label class="field"
          >规则权重（%）<input
            class="input"
            type="range"
            min="1"
            max="99"
            v-model.number="weight"
          />{{ weight }}% · 模型 {{ 100 - weight }}%</label
        ><label><input type="checkbox" v-model="blocked" /> 假设有阻断规则失败</label>
      </div>
      <p v-if="[rule, judge].some((v) => !Number.isFinite(v) || v < 0 || v > 100)" role="alert">
        请输入 0—100 的分数。
      </p>
      <template v-else
        ><p>
          计算：{{ rule }} × {{ weight }}% + {{ judge }} × {{ 100 - weight }}% =
          {{ total.toFixed(1) }} 分
        </p>
        <p>
          阈值 80 分：{{
            blocked
              ? '未通过：阻断规则失败，综合高分不能抵消'
              : total >= 80
                ? '通过'
                : '未通过：综合分数不足'
          }}。
        </p>
        <details>
          <summary>查看样例输出（计算示意，非执行报告）</summary>
          <pre>{{
            pretty({
              score: total / 100,
              outcome: blocked || total < 80 ? 'fail' : 'pass',
              blocking_failure: blocked,
              children: [
                { kind: 'rule', score: rule / 100, weight: weight / 100 },
                { kind: 'llm_judge', score: judge / 100, weight: (100 - weight) / 100 },
              ],
            })
          }}</pre>
        </details></template
      >
    </template>
    <template v-else>
      <h3>输入材料</h3>
      <p>
        请求：高风险申请是否直接批准？参考要求：必须转人工复核。实际回答样例：已转人工复核，未自动批准。
      </p>
      <h3>评分标准</h3>
      <p>事实正确、业务要求覆盖完整、结论有执行证据支持；假设模型按该标准给出 0.9。</p>
      <pre>{{
        pretty({
          outcome: 'pass',
          score: 0.9,
          reason: '示例：回答符合人工复核要求，并说明未直接批准。',
        })
      }}</pre>
      <p>
        前端显示 90 分；后端分值为 0—1。真实结果还应保存实际模型信息及请求指纹。服务失败必须显示
        ERROR / 无分数，不能用此样例替代。
      </p>
    </template>
  </section>
</template>
