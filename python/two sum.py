def two_sum(nums, target):
    for i in range(len(nums)):
        for j in range(i + 1, len(nums)):
            if nums[i] + nums[j] == target:
                return [i, j]
    return []

print(two_sum([2, 7, 11, 15], 9))

def two_sum_hash(nums, target):
    hash_table = {}
    n = len(nums)
    for i in range(n):
        complement = target - nums[i]
        if complement in hash_table:
            return [hash_table[complement], i]
        hash_table[nums[i]] = i
    return []

print(two_sum_hash([2, 7, 11, 15], 9))


