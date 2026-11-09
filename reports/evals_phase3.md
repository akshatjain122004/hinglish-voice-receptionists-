# Phase 3 eval report

**Pass rate: 22/30 (73%)**

| id | category | result | reasons |
|---|---|---|---|
| booking_001 | booking | PASS |  |
| booking_002 | booking | FAIL | runtime error: ReadTimeout:  |
| booking_003 | booking | FAIL | reply exceeds 2 sentences: '\nParso dopahar ke liye root canal ke slots available hain — dopahar ke baarah baje se ek baje tak, aur dopahar teen baje se shaam chaar baje tak. Aapko kaunsa time suit karega? Booking ke liye aapka naam bhi bata dijiye.' |
| booking_004 | booking | PASS |  |
| booking_005 | booking | FAIL | tool_calls mismatch: expected [{'tool': 'check_slots', 'args': {'service': 'whitening', 'part_of_day': 'morning'}}, {'tool': 'book_appointment', 'args': {'service': 'whitening'}}], got [{'tool': 'check_slots', 'args': {'service': 'whitening', 'date': 'kal'}}, {'tool': 'book_appointment', 'args': {'name': 'Neha', 'service': 'whitening', 'start': 'kal subah 11 baje'}}] |
| no_slot_001 | no_slot | PASS |  |
| no_slot_002 | no_slot | PASS |  |
| faq_001 | faq | PASS |  |
| faq_002 | faq | FAIL | runtime error: ReadTimeout:  |
| faq_003 | faq | PASS |  |
| faq_004 | faq | PASS |  |
| faq_005 | faq | FAIL | tool_calls mismatch: expected [{'tool': 'answer_faq', 'args': {'question': 'pediatric dental care'}}], got [{'tool': 'answer_faq', 'args': {'question': 'Do you treat children? Pediatric dentistry?'}}] |
| faq_006 | faq | PASS |  |
| faq_007 | faq | PASS |  |
| faq_008 | faq | PASS |  |
| faq_009 | faq | PASS |  |
| faq_010 | faq | FAIL | missing required mention(s): ['BDS'] |
| faq_out_of_scope_001 | faq | FAIL | tool_calls mismatch: expected [{'tool': 'answer_faq', 'args': {'question': 'MRI scan'}}], got [{'tool': 'answer_faq', 'args': {'question': 'Do you also do MRI scans here?'}}] |
| reschedule_001 | reschedule | PASS |  |
| reschedule_002 | reschedule | PASS |  |
| cancel_001 | cancel | PASS |  |
| cancel_002 | cancel | PASS |  |
| language_switch_001 | language_switch | PASS |  |
| language_switch_002 | language_switch | PASS |  |
| unclear_001 | unclear | FAIL | missing required mention(s): ['booking', 'appointment'] |
| unclear_002 | unclear | PASS |  |
| off_topic_001 | off_topic | PASS |  |
| off_topic_002 | off_topic | PASS |  |
| human_handoff_001 | human_handoff | PASS |  |
| human_handoff_002 | human_handoff | PASS |  |
