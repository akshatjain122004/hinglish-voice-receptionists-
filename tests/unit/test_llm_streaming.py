from app.llm_streaming import ChatDelta, ToolCallAccumulator, ToolCallDelta


def test_single_chunk_tool_call():
    acc = ToolCallAccumulator()
    acc.add(
        ToolCallDelta(
            index=0, id="call_1", name="check_slots", arguments_fragment='{"date": "kal"}'
        )
    )

    result = acc.finish()

    assert len(result) == 1
    assert result[0].id == "call_1"
    assert result[0].name == "check_slots"
    assert result[0].arguments == {"date": "kal"}


def test_fragmented_arguments_across_many_chunks():
    """OpenAI-compatible streaming sends `arguments` as many small string
    fragments across chunks, all needing concatenation before they parse as
    JSON. Only the first fragment for an index carries `id`/`name`."""
    acc = ToolCallAccumulator()
    acc.add(ToolCallDelta(index=0, id="call_1", name="book_appointment", arguments_fragment=""))
    acc.add(ToolCallDelta(index=0, arguments_fragment='{"name": '))
    acc.add(ToolCallDelta(index=0, arguments_fragment='"Ravi", '))
    acc.add(ToolCallDelta(index=0, arguments_fragment='"service": "cleaning"}'))

    result = acc.finish()

    assert len(result) == 1
    assert result[0].arguments == {"name": "Ravi", "service": "cleaning"}


def test_two_parallel_tool_calls_merge_by_index_not_arrival_order():
    acc = ToolCallAccumulator()
    acc.add(ToolCallDelta(index=0, id="call_1", name="check_slots", arguments_fragment='{"date"'))
    acc.add(
        ToolCallDelta(index=1, id="call_2", name="answer_faq", arguments_fragment='{"question"')
    )
    acc.add(ToolCallDelta(index=0, arguments_fragment=': "kal"}'))
    acc.add(ToolCallDelta(index=1, arguments_fragment=': "fees?"}'))

    result = acc.finish()

    assert [tc.name for tc in result] == ["check_slots", "answer_faq"]
    assert result[0].arguments == {"date": "kal"}
    assert result[1].arguments == {"question": "fees?"}


def test_no_tool_calls_returns_empty_list():
    acc = ToolCallAccumulator()

    assert acc.finish() == []


def test_chat_delta_defaults_to_no_tool_call_deltas():
    delta = ChatDelta(content="Namaste!")

    assert delta.tool_call_deltas == []
