"""Build the four importable n8n workflow files from the prompt files.

The prompts and schema in prompts/ are the single source of truth. Run this after editing them,
then re-import (see the guide, step 3b). Because each workflow has a fixed ID, re-importing
updates the existing workflow instead of creating a copy.

Usage:  python workflow/build_workflows.py
Target: n8n 2.45.x (node versions below were checked against that release).
"""
import json
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROMPTS, OUT = ROOT / "prompts", ROOT / "workflow" / "exports"

EXTRACTION_PROMPT = (PROMPTS / "extraction_system_prompt.md").read_text(encoding="utf-8").strip()
MEMO_PROMPT = (PROMPTS / "memo_prompt.md").read_text(encoding="utf-8").strip()
SCHEMA = (PROMPTS / "output_schema.json").read_text(encoding="utf-8").strip()

SUB_WORKFLOW_NAME = "Extract & Memo"
SUB_INPUTS = ["transcript", "model", "workshop_title", "workshop_date", "markets", "run_id"]
TRIGGER = "When Executed by Another Workflow"
SHEET_ID = "YOUR_GOOGLE_SHEET_ID"   # replace in n8n after import (or here, then rebuild)
ERROR_EMAIL = "you@example.com"     # replace in n8n after import
# Fixed IDs so the workflows can reference each other after a command-line import
IDS = {"sub": "ExtractMemoWf001", "main": "WorkshopDecision", "eval": "EvalExtractWf001",
       "error": "ErrorHandlerWf01"}
# Fixed webhook IDs: nodes that receive web requests (form, approval buttons, eval webhook) need
# one. The editor adds them automatically; a command-line import doesn't.
WEBHOOK_IDS = {"form": "7d1c2a4e-5b3f-4e8a-9c61-0f2d8b7a3e01",
               "approval": "7d1c2a4e-5b3f-4e8a-9c61-0f2d8b7a3e02",
               "eval": "7d1c2a4e-5b3f-4e8a-9c61-0f2d8b7a3e03"}


# ---- Small builders ---------------------------------------------------------------------
def node(name, type_, version, position, parameters, **extra):
    return {"id": str(uuid.uuid4()), "name": name, "type": type_, "typeVersion": version,
            "position": position, "parameters": parameters, **extra}


def assignments(fields):
    """fields: list of (name, value, type) for an Edit Fields (Set) node."""
    return {"assignments": [{"id": str(uuid.uuid4()), "name": n, "value": v, "type": t}
                            for n, v, t in fields]}


def condition(left, operation, right="", type_="string"):
    cond = {"id": str(uuid.uuid4()), "leftValue": left, "rightValue": right,
            "operator": {"type": type_, "operation": operation}}
    if operation in ("true", "false"):
        cond["operator"]["singleValue"] = True
    return {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict",
                        "version": 2},
            "conditions": [cond], "combinator": "and"}


def call_subworkflow(name, position, values):
    """Execute Workflow node pointing at the shared sub-workflow by its fixed ID."""
    schema = [{"id": f, "displayName": f, "required": False, "defaultMatch": False,
               "display": True, "canBeUsedToMatch": True, "type": "string", "removed": False}
              for f in SUB_INPUTS]
    return node(name, "n8n-nodes-base.executeWorkflow", 1.2, position, {
        "workflowId": {"__rl": True, "value": IDS["sub"], "mode": "list",
                       "cachedResultName": SUB_WORKFLOW_NAME},
        "workflowInputs": {"mappingMode": "defineBelow", "value": values, "matchingColumns": [],
                           "schema": schema, "attemptToConvertTypes": False,
                           "convertFieldsToString": True},
        "options": {}})


def link(*targets, type_="main", index=0):
    return {type_: [[{"node": t, "type": type_, "index": index} for t in targets]]}


def workflow(key, name, nodes, connections, settings=None):
    return {"id": IDS[key], "name": name, "nodes": nodes, "connections": connections, "pinData": {},
            "settings": {"executionOrder": "v1", **(settings or {})}, "active": False}


# ---- 1. Shared sub-workflow: Extract & Memo ----------------------------------------------
VALIDATE_JS = """const input = $('When Executed by Another Workflow').first().json;
const d = $json.output ?? $json;
for (const k of ['decisions','open_issues','actions','risks','dependencies']) d[k] = d[k] ?? [];
const flags = [];
const unowned = d.actions.filter(a => !a.owner || a.owner === 'UNASSIGNED').length;
if (unowned) flags.push(`${unowned} action(s) have no owner`);
d.risks.filter(r => r.impact === 'High' && r.likelihood === 'High' && !r.mitigation)
  .forEach(r => flags.push(`High/High risk without mitigation: ${r.risk}`));
if (d.open_issues.length) flags.push(`${d.open_issues.length} open issue(s) need escalation`);
return [{ json: { ...d, governance_flags: flags, model_used: input.model, run_id: input.run_id,
  workshop: input.workshop_title, workshop_date: input.workshop_date, markets: input.markets } }];"""

# No n8n-level retry on the LLM nodes: LangChain already retries failed calls with backoff,
# and stacking both made the switch to Groq take ~3 minutes in testing.
model_ref = "={{ $('When Executed by Another Workflow').first().json.model }}"

sub_nodes = [
    node(TRIGGER, "n8n-nodes-base.executeWorkflowTrigger", 1.1, [0, 0],
         {"workflowInputs": {"values": [{"name": f} for f in SUB_INPUTS]}}),
    node("Extract", "@n8n/n8n-nodes-langchain.informationExtractor", 1.2, [260, 0], {
        "text": "={{ $json.transcript }}", "schemaType": "manual", "inputSchema": SCHEMA,
        "options": {"systemPromptTemplate": EXTRACTION_PROMPT}}),
    node("Validate", "n8n-nodes-base.code", 2, [560, 0], {"jsCode": VALIDATE_JS}),
    node("Memo", "@n8n/n8n-nodes-langchain.chainLlm", 1.9, [800, 0], {
        "promptType": "define", "text": "=" + MEMO_PROMPT}),
    node("Package", "n8n-nodes-base.set", 3.4, [1100, 0], {
        "assignments": assignments([
            ("extraction", "={{ $('Validate').item.json }}", "object"),
            ("memo", "={{ $json.text }}", "string"),
            ("model_used", "={{ $('Validate').item.json.model_used }}", "string")]),
        "options": {}}),
    node("Model Selector", "@n8n/n8n-nodes-langchain.modelSelector", 1, [500, 260], {
        "numberInputs": 2,
        "rules": {"rule": [
            {"modelIndex": 2, "conditions": condition(model_ref, "equals", "groq")},
            {"modelIndex": 1, "conditions": condition(model_ref, "notEquals", "groq")}]}}),
    node("Gemini Flash-Lite", "@n8n/n8n-nodes-langchain.lmChatGoogleGemini", 1.2, [380, 460], {
        "modelName": "models/gemini-3.1-flash-lite",
        "options": {"temperature": 0.1, "maxOutputTokens": 8192}}),
    node("Groq gpt-oss-120b", "@n8n/n8n-nodes-langchain.lmChatGroq", 1, [620, 460], {
        "model": "openai/gpt-oss-120b",
        "options": {"temperature": 0.1, "maxTokensToSample": 8192}}),
]
sub_connections = {
    TRIGGER: link("Extract"),
    "Extract": link("Validate"),
    "Validate": link("Memo"),
    "Memo": link("Package"),
    "Model Selector": link("Extract", "Memo", type_="ai_languageModel"),
    "Gemini Flash-Lite": link("Model Selector", type_="ai_languageModel", index=0),
    "Groq gpt-oss-120b": link("Model Selector", type_="ai_languageModel", index=1),
}
# Sub-workflows called from other workflows must allow it:
sub_wf = workflow("sub", SUB_WORKFLOW_NAME, sub_nodes, sub_connections,
                  {"callerPolicy": "workflowsFromSameOwner"})


# ---- 2. Main workflow: Workshop to Decision ----------------------------------------------
FORM = "On form submission"
ef = "$('Edit Fields').item.json"
sub_values = {
    "transcript": f"={{{{ {ef}.notes }}}}",
    "workshop_title": f"={{{{ {ef}.workshop_title }}}}",
    "workshop_date": f"={{{{ {ef}.workshop_date }}}}",
    "markets": f"={{{{ {ef}.markets_text }}}}",
    "run_id": f"={{{{ {ef}.run_id }}}}",
}


def rows_js(key, mapping):
    fields = ",\n    ".join(f"{col}: {expr}" for col, expr in mapping.items())
    return (f"const m = $('Memo to HTML').first().json;\nconst e = m.extraction;\n"
            f"const createdAt = $('Edit Fields').first().json.created_at;\n"
            f"return (e.{key} || []).map(x => ({{ json: {{\n    {fields}\n}} }}));")


base_cols = {"run_id": "e.run_id", "workshop": "e.workshop"}
actions_js = rows_js("actions", {**base_cols, "action": "x.action", "owner": "x.owner ?? 'UNASSIGNED'",
                                 "due_date": "x.due_date ?? ''", "priority": "x.priority ?? ''",
                                 "linked_decision": "x.linked_decision ?? ''", "status": "'Open'",
                                 "model_used": "e.model_used", "created_at": "createdAt"})
risks_js = rows_js("risks", {**base_cols, "risk": "x.risk", "impact": "x.impact ?? ''",
                             "likelihood": "x.likelihood ?? ''", "mitigation": "x.mitigation ?? ''",
                             "owner": "x.owner ?? ''", "source": "x.source ?? ''"})
decisions_js = rows_js("decisions", {**base_cols, "decision": "x.decision",
                                     "rationale": "x.rationale ?? ''", "scope": "x.scope ?? ''",
                                     "decision_owner": "x.decision_owner ?? ''",
                                     "requires_signoff": "x.requires_signoff ?? ''"})


def sheet_append(name, tab, position):
    return node(name, "n8n-nodes-base.googleSheets", 4.5, position, {
        "operation": "append",
        "documentId": {"__rl": True, "value": SHEET_ID, "mode": "id"},
        "sheetName": {"__rl": True, "value": tab, "mode": "name"},
        "columns": {"mappingMode": "autoMapInputData", "value": {}, "matchingColumns": [],
                    "schema": []},
        "options": {}})


m2h = "$('Memo to HTML').item.json"
flags_text = f"{{{{ ({m2h}.extraction.governance_flags || []).map(f => '- ' + f).join('\\n') || '- none' }}}}"

main_nodes = [
    node(FORM, "n8n-nodes-base.formTrigger", 2.5, [0, 0], {
        "formTitle": "Workshop to Decision",
        "formDescription": "Paste the notes or transcript from a cross-functional workshop. "
                           "You'll get a draft decision memo to approve by email.",
        "formFields": {"values": [
            {"fieldLabel": "Workshop title", "fieldName": "workshop_title", "requiredField": True},
            {"fieldLabel": "Workshop date", "fieldName": "workshop_date", "fieldType": "date"},
            {"fieldLabel": "Markets in scope", "fieldName": "markets", "fieldType": "checkbox",
             "fieldOptions": {"values": [{"option": o} for o in ["DK", "SE", "NO", "FI", "Group"]]}},
            {"fieldLabel": "Notes or transcript", "fieldName": "notes", "fieldType": "textarea",
             "requiredField": True},
            {"fieldLabel": "Decision owner / approver email", "fieldName": "approver_email",
             "fieldType": "email", "requiredField": True},
            {"fieldLabel": "Facilitator email", "fieldName": "facilitator_email",
             "fieldType": "email", "requiredField": True}]},
        "options": {"path": "workshop-to-decision", "buttonLabel": "Create decision memo"}}, webhookId=WEBHOOK_IDS["form"]),
    node("Edit Fields", "n8n-nodes-base.set", 3.4, [220, 0], {
        "assignments": assignments([
            ("run_id", "={{ $now.toFormat('yyyyMMdd-HHmmss') }}", "string"),
            ("created_at", "={{ $now.toISO() }}", "string"),
            ("markets_text", "={{ [].concat($json.markets ?? []).join(', ') }}", "string")]),
        "includeOtherFields": True, "options": {}}),
    {**call_subworkflow("Call – Gemini", [440, 0], {**sub_values, "model": "gemini"}),
     "onError": "continueErrorOutput"},
    call_subworkflow("Call – Groq fallback", [660, 160], {**sub_values, "model": "groq"}),
    node("Memo to HTML", "n8n-nodes-base.markdown", 1, [880, 0], {
        "mode": "markdownToHtml", "markdown": "={{ $json.memo }}", "destinationKey": "memo_html",
        "options": {"tables": True}}),
    node("Send memo for review", "n8n-nodes-base.gmail", 2.1, [1100, 0], {
        "sendTo": f"={{{{ {ef}.approver_email }}}}",
        "subject": f"=[For review] {{{{ {ef}.workshop_title }}}}: decision memo",
        "emailType": "html",
        "message": f"={{{{ {m2h}.memo_html }}}}<hr><p><b>Drafted by:</b> {{{{ {m2h}.model_used }}}}"
                   f" &middot; <b>Run ID:</b> {{{{ {ef}.run_id }}}}</p>"
                   "<p>An approval request follows in a separate email.</p>",
        "options": {"appendAttribution": False}}),
    node("Ask for approval", "n8n-nodes-base.gmail", 2.1, [1320, 0], {
        "operation": "sendAndWait",
        "sendTo": f"={{{{ {ef}.approver_email }}}}",
        "subject": f"=[Approval needed] {{{{ {ef}.workshop_title }}}}",
        "message": f"=Please review the decision memo for \"{{{{ {ef}.workshop_title }}}}\" "
                   "(sent to you in the previous email) and approve or reject it.\n\n"
                   f"Governance flags:\n{flags_text}\n\n"
                   f"Drafted by: {{{{ {m2h}.model_used }}}}. Nothing is shared until you approve.",
        "approvalOptions": {"values": {"approvalType": "double", "approveLabel": "Approve memo",
                                       "disapproveLabel": "Reject"}},
        "options": {"appendAttribution": False}}, webhookId=WEBHOOK_IDS["approval"]),
    node("Approved?", "n8n-nodes-base.if", 2.2, [1540, 0], {
        "conditions": condition("={{ $json.data.approved }}", "true", type_="boolean"),
        "options": {}}),
    node("Rows – Actions", "n8n-nodes-base.code", 2, [1780, -300], {"jsCode": actions_js}),
    node("Rows – Risks", "n8n-nodes-base.code", 2, [1780, -120], {"jsCode": risks_js}),
    node("Rows – Decisions", "n8n-nodes-base.code", 2, [1780, 60], {"jsCode": decisions_js}),
    sheet_append("Sheets – Actions", "Actions", [2000, -300]),
    sheet_append("Sheets – Risks", "Risks", [2000, -120]),
    sheet_append("Sheets – Decisions", "Decisions", [2000, 60]),
    node("Send final memo", "n8n-nodes-base.gmail", 2.1, [1780, 240], {
        "sendTo": f"={{{{ {ef}.approver_email }}}}, {{{{ {ef}.facilitator_email }}}}",
        "subject": f"=[Approved] {{{{ {ef}.workshop_title }}}}: decision memo",
        "emailType": "html", "message": f"={{{{ {m2h}.memo_html }}}}",
        "options": {"appendAttribution": False}}),
    node("Notify: memo rejected", "n8n-nodes-base.gmail", 2.1, [1780, 420], {
        "sendTo": f"={{{{ {ef}.facilitator_email }}}}",
        "subject": f"=[Rejected] {{{{ {ef}.workshop_title }}}}: decision memo",
        "emailType": "text",
        "message": f"=The decision owner rejected the AI-drafted memo for \"{{{{ {ef}.workshop_title }}}}\". "
                   "Nothing was published to the trackers. Please revise the notes or the memo "
                   "with the decision owner and resubmit.",
        "options": {"appendAttribution": False}}),
]
main_connections = {
    FORM: link("Edit Fields"),
    "Edit Fields": link("Call – Gemini"),
    "Call – Gemini": {"main": [[{"node": "Memo to HTML", "type": "main", "index": 0}],
                               [{"node": "Call – Groq fallback", "type": "main", "index": 0}]]},
    "Call – Groq fallback": link("Memo to HTML"),
    "Memo to HTML": link("Send memo for review"),
    "Send memo for review": link("Ask for approval"),
    "Ask for approval": link("Approved?"),
    "Approved?": {"main": [
        [{"node": n, "type": "main", "index": 0}
         for n in ["Rows – Actions", "Rows – Risks", "Rows – Decisions", "Send final memo"]],
        [{"node": "Notify: memo rejected", "type": "main", "index": 0}]]},
    "Rows – Actions": link("Sheets – Actions"),
    "Rows – Risks": link("Sheets – Risks"),
    "Rows – Decisions": link("Sheets – Decisions"),
}
main_wf = workflow("main", "Workshop to Decision", main_nodes, main_connections,
                   {"errorWorkflow": IDS["error"]})


# ---- 3. Eval webhook ----------------------------------------------------------------------
eval_nodes = [
    node("Webhook", "n8n-nodes-base.webhook", 2, [0, 0], {
        "httpMethod": "POST", "path": "eval-extract", "responseMode": "responseNode",
        "options": {}}, webhookId=WEBHOOK_IDS["eval"]),
    call_subworkflow("Call Extract & Memo", [240, 0], {
        "transcript": "={{ $json.body.transcript }}", "model": "={{ $json.body.model }}",
        "workshop_title": "Evaluation run", "workshop_date": "", "markets": "",
        "run_id": "=eval-{{ $now.toMillis() }}"}),
    node("Respond to Webhook", "n8n-nodes-base.respondToWebhook", 1.1, [480, 0], {
        "respondWith": "firstIncomingItem", "options": {}}),
]
eval_connections = {"Webhook": link("Call Extract & Memo"),
                    "Call Extract & Memo": link("Respond to Webhook")}
eval_wf = workflow("eval", "Eval – Extract", eval_nodes, eval_connections,
                   {"errorWorkflow": IDS["error"]})


# ---- 4. Error handler ---------------------------------------------------------------------
err_nodes = [
    node("Error Trigger", "n8n-nodes-base.errorTrigger", 1, [0, 0], {}),
    node("Email me the error", "n8n-nodes-base.gmail", 2.1, [240, 0], {
        "sendTo": ERROR_EMAIL,
        "subject": "=[n8n error] {{ $json.workflow.name }}",
        "emailType": "text",
        "message": "=Workflow: {{ $json.workflow.name }}\nNode: {{ $json.execution.lastNodeExecuted }}\n"
                   "Error: {{ $json.execution.error.message }}\nExecution: {{ $json.execution.url }}",
        "options": {"appendAttribution": False}}),
]
err_wf = workflow("error", "Error Handler", err_nodes, {"Error Trigger": link("Email me the error")})


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for filename, wf in [("extract_and_memo.json", sub_wf), ("workshop_to_decision.json", main_wf),
                         ("eval_extract.json", eval_wf), ("error_handler.json", err_wf)]:
        (OUT / filename).write_text(json.dumps(wf, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"wrote workflow/exports/{filename}  ({len(wf['nodes'])} nodes)")
