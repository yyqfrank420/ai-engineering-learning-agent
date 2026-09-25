import type { GraphData, NodeType } from '../../../types';

// Regression fixture for mixed generic zones and a component-only expansion.
const components: Array<[string, string, NodeType, string]> = [
  ['client', 'Customer Chat Client', 'client', 'Runtime'],
  ['gateway', 'Conversation API Gateway', 'gateway', 'Runtime'],
  ['agent', 'Support Agent Orchestrator', 'service', 'Runtime'],
  ['retrieval', 'Knowledge Retrieval Service', 'service', 'Runtime'],
  ['tickets', 'Conversation and Ticket Store', 'datastore', 'Data'],
  ['knowledge', 'Knowledge Base Store', 'datastore', 'Data'],
  ['validator', 'Response Grounding Validator', 'service', 'Operations'],
  ['audit', 'Audit Log', 'datastore', 'Operations'],
  ['human', 'Human Escalation Console', 'client', 'Operations'],
  ['executor', 'CRM Ticket Executor', 'service', 'External'],
  ['crm', 'Support CRM', 'external', 'External'],
];

export const learnerSupportGraph: GraphData = {
  graph_type: 'architecture', title: 'AI customer support agent', design_origin: 'applied',
  nodes: components.map(([id, label, type, group]) => ({
    id, label, type, technology: type === 'datastore' ? 'Data store' : type === 'service' ? 'Application service' : type,
    description: label, detail: null, design_origin: 'applied',
    lane: group === 'Operations' ? 'bottom' : 'main',
  })),
  groups: ['Runtime', 'Data', 'Operations', 'External'].map(label => ({
    id: label.toLowerCase(), label, kind: 'runtime', nodeIds: components.filter(component => component[3] === label).map(component => component[0]),
  })),
  edges: [['client', 'gateway'], ['gateway', 'agent'], ['agent', 'retrieval'], ['retrieval', 'knowledge'],
    ['agent', 'tickets'], ['agent', 'validator'], ['validator', 'audit'], ['agent', 'human'], ['agent', 'executor'], ['executor', 'crm']]
    .map(([source, target]) => ({ source, target, label: 'Request', technology: 'HTTPS', sync: 'sync', description: '', flow: 'runtime' })),
  sequence: [],
};
