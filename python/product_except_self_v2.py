from typing import List

def product_except_self(nums: List[int]) -> List[int]:
    n = len(nums)

    # left[i] = nums[0] * nums[1] * ... * nums[i-1]   (i 左边所有数的乘积)
    left = [1] * n
    for i in range(1, n):
        left[i] = left[i - 1] * nums[i - 1]

    # right[i] = nums[i+1] * nums[i+2] * ... * nums[n-1]   (i 右边所有数的乘积)
    right = [1] * n
    for i in range(n - 2, -1, -1):
        right[i] = right[i + 1] * nums[i + 1]

    # 结果 = 左边 × 右边
    result = [left[i] * right[i] for i in range(n)]
    return result


# 测试
print(product_except_self([1, 2, 3, 4]))  # [24, 12, 8, 6]
