# Phase 2 eval report

**Pass rate: 14/25 (56%)**

| id | category | result | reasons |
|---|---|---|---|
| booking_001 | booking | PASS |  |
| booking_002 | booking | FAIL | tool_calls mismatch: expected [{'tool': 'check_slots', 'args': {'service': 'consultation', 'part_of_day': 'morning'}}, {'tool': 'book_appointment', 'args': {'service': 'consultation'}}], got [{'tool': 'check_slots', 'args': {'date': 'tomorrow', 'service': 'consultation', 'part_of_day': 'morning'}}] |
| booking_003 | booking | FAIL | tool_calls mismatch: expected [{'tool': 'check_slots', 'args': {'service': 'root_canal', 'part_of_day': 'afternoon'}}, {'tool': 'book_appointment', 'args': {'service': 'root_canal'}}], got [{'tool': 'check_slots', 'args': {'service': 'root_canal', 'date': 'parso', 'part_of_day': 'afternoon'}}] |
| booking_004 | booking | PASS |  |
| booking_005 | booking | FAIL | tool_calls mismatch: expected [{'tool': 'check_slots', 'args': {'service': 'whitening', 'part_of_day': 'morning'}}, {'tool': 'book_appointment', 'args': {'service': 'whitening'}}], got [{'tool': 'check_slots', 'args': {'date': 'kal', 'service': 'whitening'}}] |
| no_slot_001 | no_slot | FAIL | tool_calls mismatch: expected [{'tool': 'check_slots', 'args': {'service': 'cleaning'}}], got [] |
| no_slot_002 | no_slot | PASS |  |
| faq_001 | faq | FAIL | missing required mention(s): ['500'] |
| faq_002 | faq | FAIL | tool_calls mismatch: expected [{'tool': 'answer_faq', 'args': {'question': 'clinic opening time'}}], got [{'tool': 'answer_faq', 'args': {'question': 'What time does the clinic open?'}}]; missing required mention(s): ['10'] |
| faq_003 | faq | PASS |  |
| faq_004 | faq | PASS |  |
| faq_005 | faq | FAIL | tool_calls mismatch: expected [{'tool': 'answer_faq', 'args': {'question': 'pediatric dental care'}}], got [{'tool': 'answer_faq', 'args': {'question': 'Bachon ka treatment karte ho aap?'}}] |
| faq_out_of_scope_001 | faq | FAIL | tool_calls mismatch: expected [{'tool': 'answer_faq', 'args': {'question': 'MRI scan'}}], got []; missing required mention(s): ['staff', 'confirm'] |
| reschedule_001 | reschedule | PASS |  |
| reschedule_002 | reschedule | FAIL | tool_calls mismatch: expected [{'tool': 'reschedule_appointment', 'args': {}}], got []; possible hallucinated number in a reply |
| cancel_001 | cancel | FAIL | reply exceeds 2 sentences: '\nMujhe system mein koi confirmed appointment nahi mil raha hai. Kya aapka naam ya phone number kuch alag hai? Ya phir main aapko staff se connect karwa doon?' |
| cancel_002 | cancel | PASS |  |
| language_switch_001 | language_switch | PASS |  |
| language_switch_002 | language_switch | PASS |  |
| unclear_001 | unclear | FAIL | missing required mention(s): ['booking', 'appointment'] |
| unclear_002 | unclear | PASS |  |
| off_topic_001 | off_topic | PASS |  |
| off_topic_002 | off_topic | PASS |  |
| human_handoff_001 | human_handoff | PASS |  |
| human_handoff_002 | human_handoff | PASS |  |
