# Phase 5 eval report

**Pass rate: 30/35 (86%)**

| id | category | result | reasons |
|---|---|---|---|
| booking_001 | booking | PASS |  |
| booking_002 | booking | FAIL | runtime error: ReadTimeout:  |
| booking_003 | booking | PASS |  |
| booking_004 | booking | PASS |  |
| booking_005 | booking | PASS |  |
| no_slot_001 | no_slot | PASS |  |
| no_slot_002 | no_slot | PASS |  |
| faq_001 | faq | PASS |  |
| faq_002 | faq | PASS |  |
| faq_003 | faq | PASS |  |
| faq_004 | faq | PASS |  |
| faq_005 | faq | PASS |  |
| faq_006 | faq | PASS |  |
| faq_007 | faq | PASS |  |
| faq_008 | faq | PASS |  |
| faq_009 | faq | PASS |  |
| faq_010 | faq | PASS |  |
| faq_out_of_scope_001 | faq | FAIL | tool_calls mismatch: expected [{'tool': 'answer_faq', 'args': {'question': 'MRI scan'}}], got []; missing required mention(s): ['staff', 'confirm'] |
| reschedule_001 | reschedule | PASS |  |
| reschedule_002 | reschedule | FAIL | tool_calls mismatch: expected [{'tool': 'reschedule_appointment', 'args': {}}], got []; possible hallucinated number in a reply |
| cancel_001 | cancel | PASS |  |
| cancel_002 | cancel | PASS |  |
| language_switch_001 | language_switch | PASS |  |
| language_switch_002 | language_switch | PASS |  |
| unclear_001 | unclear | PASS |  |
| unclear_002 | unclear | PASS |  |
| off_topic_001 | off_topic | PASS |  |
| off_topic_002 | off_topic | PASS |  |
| human_handoff_001 | human_handoff | PASS |  |
| human_handoff_002 | human_handoff | PASS |  |
| code_switch_001 | code_switch | PASS |  |
| code_switch_002 | code_switch | PASS |  |
| code_switch_003 | code_switch | FAIL | possible hallucinated number in a reply |
| code_switch_004 | code_switch | PASS |  |
| code_switch_005 | code_switch | FAIL | runtime error: ReadTimeout:  |
