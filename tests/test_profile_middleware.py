"""用户画像提取中间件测试"""

from src.memory.profile_middleware import ProfileExtractionResult


def test_profile_extraction_result_normalizes_empty_string_preferences():
    """空字符串 preferences 应被归一为字典，避免画像提取整体失败"""
    result = ProfileExtractionResult.model_validate(
        {
            "role": "门店老板",
            "topics": ["会员复购率"],
            "preferences": "",
        }
    )

    assert result.role == "门店老板"
    assert result.topics == ["会员复购率"]
    assert result.preferences == {}
