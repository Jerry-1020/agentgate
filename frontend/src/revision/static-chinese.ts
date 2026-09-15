// Exact-text Chinese translations of existing historical report content; raw reports remain unchanged.
const translations:Record<string,string>={
  "Both skills involve processing loan applications, but their declared responsibilities are distinct: one retrieves a risk classification, while the other assesses the application and chooses an approval action. The assessment in 'Loan Approval' likely depends on the risk classification from 'Credit Inquiry', indicating a sequential or dependent relationship rather than a direct conflict or duplication.": "两个技能都处理贷款申请，但声明的职责不同：一个查询风险分类，另一个评估申请并选择审批动作。“贷款审批”的评估可能依赖“征信查询”的风险分类，说明两者可能存在先后或依赖关系，而非直接冲突或重复。",
  "Clarify that 'Credit Inquiry' is a sub-step or input for 'Loan Approval', or specify that risk classification retrieval is a separate, preliminary service.": "明确“征信查询”是“贷款审批”的子步骤或输入，或说明风险分类查询是独立的前置服务。",
  "What's the risk level for this loan?": "这笔贷款的风险等级是什么？",
  "Should I approve this loan application?": "我应该批准这份贷款申请吗？",
  "Evaluate this loan request.": "评估这笔贷款申请。",
  "Both skills involve processing a loan application, but they focus on distinct steps: one on approval decisions, the other on calculating repayment terms. Routing can be clear if the user request specifies either approval assessment or installment calculation.": "两个技能都涉及贷款申请，但关注不同步骤：一个负责审批决策，另一个计算还款条件。若用户请求明确指定审批评估或分期计算，路由就可以清晰区分。",
  "Clarify descriptions to specify that 'Loan Approval' handles approval decisions and 'Repayment Plan' focuses on post-approval installment calculations.": "明确职责描述：“贷款审批”处理审批决策，“还款计划”负责审批后的分期计算。",
  "What's next for my loan application?": "我的贷款申请下一步是什么？",
  "Can you process my loan?": "能处理我的贷款吗？",
  "I need help with my loan details.": "我需要贷款详情方面的帮助。",
  "Both Skills involve processing loan applications, but with distinct primary responsibilities: Credit Inquiry focuses on retrieving risk classification, while Loan Approval focuses on assessing the application and choosing an approval action. However, a request like 'Check the risk level for this loan application' could logically route to either, as risk classification is a key input for approval decisions.": "两个技能都处理贷款申请，但主要职责不同：“征信查询”查询风险分类，“贷款审批”评估申请并选择审批动作。不过，“查看这份贷款申请的风险等级”这样的请求可能合理地路由到任一技能，因为风险分类是审批决策的重要输入。",
  "Clarify that Credit Inquiry is a data retrieval step, while Loan Approval is a decision-making step. Consider making Credit Inquiry a prerequisite or sub-task within the Loan Approval workflow to avoid routing ambiguity.": "明确“征信查询”是数据查询步骤，“贷款审批”是决策步骤。可考虑将征信查询作为贷款审批流程的前置条件或子任务，以避免路由歧义。",
  "Check the risk level for this loan application": "查看这份贷款申请的风险等级",
  "Evaluate this loan application for approval": "评估这份贷款申请是否可批准",
  "What is the risk classification and can we approve this loan?": "风险分类是什么，我们能批准这笔贷款吗？",
  "Both skills involve processing a loan application, but their core responsibilities are distinct: one focuses on approval decisions, the other on calculating repayment terms. Routing can be clear based on whether the user's request is about approval status or payment calculations.": "两个技能都涉及贷款申请，但核心职责不同：一个关注审批决策，另一个计算还款条件。可根据用户询问的是审批状态还是还款计算来明确路由。",
  "Clarify descriptions to emphasize 'approval decision' vs. 'payment calculation' to reduce ambiguity.": "在职责描述中突出“审批决策”与“还款计算”的区别，以减少歧义。",
  "What are the next steps for my loan?": "我的贷款接下来有哪些步骤？",
  "Can you process my loan application?": "能处理我的贷款申请吗？",
  "I need help with my loan.": "我的贷款需要帮助。"
}
export const staticChinese=(text:string)=>translations[text]??text
export const skillChinese=(text:string)=>({ 'Credit Inquiry':'征信查询','Loan Approval':'贷款审批','Repayment Plan':'还款计划','Complaint':'投诉处理','credit_inquiry':'征信查询','loan_approval':'贷款审批','repayment_plan':'还款计划','complaint':'投诉处理'} as Record<string,string>)[text]??text

