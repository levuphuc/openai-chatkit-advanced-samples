from agents import FileSearchTool, Agent, ModelSettings, TResponseInputItem, Runner, RunConfig, trace
from pydantic import BaseModel

# Tool definitions
file_search = FileSearchTool(
  vector_store_ids=[
    "vs_69019b97c71c8191b4eba8d2aab7e561"
  ]
)
classify = Agent(
  name="Classify",
  instructions="""
Phân loại câu hỏi thành một từ: GREET, SENSITIVE, BUDDHISM hoặc OTHER.
- GREET: Câu chào hỏi, xã giao, cảm ơn, không phải câu hỏi thực sự. Ví dụ: "Chào thầy", "Thầy khỏe không", "Cảm ơn", "Dạ", "Chúc ngủ ngon", "Tạm biệt".
- SENSITIVE: Nội dung chính trị, phân biệt chủng tộc, tôn giáo ngoài Phật giáo, bạo lực, 18+, thù ghét, tự tử, công kích cá nhân. Ví dụ: "Thầy nghĩ gì về chính phủ?", "Thiên Chúa giáo hay hơn?", "Làm sao trả thù?"
- BUDDHISM: Câu hỏi liên quan đến Phật học hoặc kiến thức Phật pháp. Ví dụ: "Duyên khởi là gì?", "Kinh Kim Cang nói gì?", "Làm sao bớt sân hận?"
- OTHER: Không thuộc ba loại trên, không liên quan Phật học, không chủ đề nhạy cảm, bao gồm cả câu hỏi thực tế, học hỏi, cầu đạo. Ví dụ: "AI là gì?", "Thời tiết hôm nay?", "Viết giúp con đoạn code Python", "Cách nấu phở", "Kinh tế Việt Nam 2025 thế nào?"
Chỉ trả về một từ duy nhất: "GREET" hoặc "SENSITIVE" hoặc "BUDDHISM" hoặc "OTHER"
  """,
  model="gpt-4o-mini",
  model_settings=ModelSettings(
    temperature=0.1,
    top_p=0.1,
    max_tokens=1024,
    store=True
  )
)


buddhism_agent = Agent(
  name="Buddhism Agent",
  instructions="[Role] - Đóng vai: Hòa thượng Tuệ Sỹ. Xưng thầy, gọi con. Giọng: ôn tồn, từ bi. Văn phong: súc tích, mạch lạc. [Instructions] - Chỉ sử dụng kiến thức từ KB đã cung cấp. - Không suy diễn ngoài phạm vi KB. - Trả lời ngắn gọn (1-3 đoạn), tập trung vào trọng điểm.",
  model="gpt-4o-mini",
  tools=[
    file_search
  ],
  model_settings=ModelSettings(
    temperature=0.5,
    top_p=0.5,
    max_tokens=2048,
    store=True
  )
)


refuse_agent = Agent(
  name="Refuse Agent",
  instructions="[Role] - Đóng vai: Hòa thượng Tuệ Sỹ - Xưng thầy, gọi con - Giọng: ôn tồn, từ bi - Văn phong: súc tích, mạch lạc [Instructions] - Chỉ hướng dẫn, trả lời các câu hỏi liên quan đến: • Kinh, luật, luận Phật giáo • Tu tập, thiền định, niệm Phật • Thuật ngữ và triết lý Phật học • Lịch sử Phật giáo. Tuyệt đối từ chối hoặc không trả lời các câu hỏi ngoài các lĩnh vực này, đặc biệt là những chủ đề nhạy cảm hoặc gây tranh cãi.",
  model="gpt-4o-mini",
  model_settings=ModelSettings(
    temperature=0.25,
    top_p=0.25,
    max_tokens=1024,
    store=True
  )
)


greet_agent = Agent(
  name="Greet Agent",
  instructions="""<Role>
Hòa thượng Tuệ Sỹ, xưng thầy, gọi con. Giọng: ôn tồn, từ bi..
<Instruction>
Hãy đáp lại lời chào""",
  model="gpt-4o-mini",
  model_settings=ModelSettings(
    temperature=0.25,
    top_p=0.25,
    max_tokens=1024,
    store=True
  )
)


query_rewrite_agent = Agent(
  name="Query Rewrite Agent",
  instructions="Vai trò: Bạn là \"Query Reformulator \", giúp cải thiện câu hỏi của người dùng trước khi truy xuất để phù hợp hơn với Knowledge Base.",
  model="gpt-4o-mini",
  model_settings=ModelSettings(
    temperature=0.4,
    top_p=0.4,
    max_tokens=1024,
    store=True
  )
)


class WorkflowInput(BaseModel):
  input_as_text: str


# Orchestrator function that classifies and returns the appropriate agent
async def get_agent_for_message(message: str) -> Agent:
    """Classify the message and return the appropriate agent to handle it."""
    # Step 1: Classify the question
    classify_result = await Runner.run(
        classify,
        input=message,
        run_config=RunConfig(trace_metadata={
            "__trace_source__": "agent-builder",
            "workflow_id": "wf_69019a037e108190b05a5a2f57cf6ada089aa45cab508faa"
        })
    )
    
    classification = classify_result.final_output_as(str).strip().upper()
    
    # Step 2: Return the appropriate agent based on classification
    if classification == "GREET":
        return greet_agent
    elif classification == "BUDDHISM":
        return buddhism_agent
    else:  # SENSITIVE, OTHER, or anything else
        return refuse_agent


# Export the Buddhism agent as the default assistant_agent
# This will be used by ChatKit, but we'll override the respond() method to use orchestrate_workflow
assistant_agent = buddhism_agent


# Main code entrypoint
async def run_workflow(workflow_input: WorkflowInput):
  with trace("Phật học RAG"):
    state = {

    }
    workflow = workflow_input.model_dump()
    conversation_history: list[TResponseInputItem] = [
      {
        "role": "user",
        "content": [
          {
            "type": "input_text",
            "text": workflow["input_as_text"]
          }
        ]
      }
    ]
    classify_result_temp = await Runner.run(
      classify,
      input=[
        *conversation_history,
        {
          "role": "user",
          "content": [
            {
              "type": "input_text",
              "text": f"Question: {workflow["input_as_text"]}"
            }
          ]
        }
      ],
      run_config=RunConfig(trace_metadata={
        "__trace_source__": "agent-builder",
        "workflow_id": "wf_69019a037e108190b05a5a2f57cf6ada089aa45cab508faa"
      })
    )
    classify_result = {
      "output_text": classify_result_temp.final_output_as(str)
    }
    if classify_result["output_text"] == "GREET":
      greet_agent_result_temp = await Runner.run(
        greet_agent,
        input=[
          *conversation_history
        ],
        run_config=RunConfig(trace_metadata={
          "__trace_source__": "agent-builder",
          "workflow_id": "wf_69019a037e108190b05a5a2f57cf6ada089aa45cab508faa"
        })
      )
      greet_agent_result = {
        "output_text": greet_agent_result_temp.final_output_as(str)
      }
    elif classify_result["output_text"] == "BUDDHISM":
      query_rewrite_agent_result_temp = await Runner.run(
        query_rewrite_agent,
        input=[
          *conversation_history
        ],
        run_config=RunConfig(trace_metadata={
          "__trace_source__": "agent-builder",
          "workflow_id": "wf_69019a037e108190b05a5a2f57cf6ada089aa45cab508faa"
        })
      )
      query_rewrite_agent_result = {
        "output_text": query_rewrite_agent_result_temp.final_output_as(str)
      }
      buddhism_agent_result_temp = await Runner.run(
        buddhism_agent,
        input=[
          *conversation_history
        ],
        run_config=RunConfig(trace_metadata={
          "__trace_source__": "agent-builder",
          "workflow_id": "wf_69019a037e108190b05a5a2f57cf6ada089aa45cab508faa"
        })
      )

      conversation_history.extend([item.to_input_item() for item in buddhism_agent_result_temp.new_items])

      buddhism_agent_result = {
        "output_text": buddhism_agent_result_temp.final_output_as(str)
      }
    elif classify_result["output_text"] == "SENSITIVE":
      refuse_agent_result_temp = await Runner.run(
        refuse_agent,
        input=[
          *conversation_history
        ],
        run_config=RunConfig(trace_metadata={
          "__trace_source__": "agent-builder",
          "workflow_id": "wf_69019a037e108190b05a5a2f57cf6ada089aa45cab508faa"
        })
      )
      refuse_agent_result = {
        "output_text": refuse_agent_result_temp.final_output_as(str)
      }
    elif classify_result["output_text"] == "OTHER":
      refuse_agent_result_temp = await Runner.run(
        refuse_agent,
        input=[
          *conversation_history
        ],
        run_config=RunConfig(trace_metadata={
          "__trace_source__": "agent-builder",
          "workflow_id": "wf_69019a037e108190b05a5a2f57cf6ada089aa45cab508faa"
        })
      )
      refuse_agent_result = {
        "output_text": refuse_agent_result_temp.final_output_as(str)
      }
    else:
      refuse_agent_result_temp = await Runner.run(
        refuse_agent,
        input=[
          *conversation_history
        ],
        run_config=RunConfig(trace_metadata={
          "__trace_source__": "agent-builder",
          "workflow_id": "wf_69019a037e108190b05a5a2f57cf6ada089aa45cab508faa"
        })
      )
      refuse_agent_result = {
        "output_text": refuse_agent_result_temp.final_output_as(str)
      }
