from typing import List

def three_sum(nums: List[int]) -> List[List[int]]:
    nums.sort()
    n = len(nums)
    result = []

    for i in range(n - 2):
        # 跳过重复的 i
        if i > 0 and nums[i] == nums[i - 1]:
            continue
        # 剪枝：当前最小和 > 0，后面更大，退出
        if nums[i] + nums[i + 1] + nums[i + 2] > 0:
            break
        # 剪枝：当前数 + 最大两个 < 0，跳过
        if nums[i] + nums[n - 2] + nums[n - 1] < 0:
            continue

        left, right = i + 1, n - 1
        while left < right:
            total = nums[i] + nums[left] + nums[right]
            if total == 0:
                result.append([nums[i], nums[left], nums[right]])
                left += 1
                right -= 1
                # 跳过重复
                while left < right and nums[left] == nums[left - 1]:
                    left += 1
                while left < right and nums[right] == nums[right + 1]:
                    right -= 1
            elif total < 0:
                left += 1
            else:
                right -= 1

    return result


# 测试
print(three_sum([-1, 0, 1, 2, -1, -4]))  # [[-1, -1, 2], [-1, 0, 1]]
print(three_sum([0, 1, 1]))              # []
print(three_sum([0, 0, 0]))              # [[0, 0, 0]]
