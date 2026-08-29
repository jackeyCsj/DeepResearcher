from typing import List

class Solution:
    def moveZeroes(self, nums: List[int]) -> None:
        """
        Do not return anything, modify nums in-place instead.
        """
        pf = pr = 0
        length = len(nums)
        for i in range(0,length):
            pf = i
            if nums[i] != 0:
                pf += 1
                pr = pf
            else:
                while pr < length - 1 and nums[pr] == 0:
                    pr +=1
                nums[pf],nums[pr] = nums[pr],nums[pf]
                print(nums)

if __name__ == "__main__":
    solution = Solution()
    nums = [0, 1, 0, 3, 12,4,5,20,0,0,40]
    solution.moveZeroes(nums)
    print(nums)  # Output: [1, 3, 12, 0, 0]