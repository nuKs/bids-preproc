import collections  # for sequence type unpacking in higher order functions
from typing import Set
import dask
from . import LocalScheduler


class DaskScheduler(LocalScheduler):
    def __init__(self, historyCachePath: str, client: dask.distributed.Client):
        super().__init__(historyCachePath)

        self._client = client

    def runTask(self, taskName: str, taskFn, cleanupFn, *args, **kwargs) -> \
        bool:
        client = self._client

        # Merge task and cleanup together in order to execute the cleanup
        # within the worker node.
        def mergedTaskAndCleanupFn(*args, **kwargs):
            result = taskFn(*args, **kwargs)
            ignoredResult = cleanupFn(result.didSucceed, *args, **kwargs)
            return result

        # Wrap task to dask.
        def blockingTaskFn(*args, **kwargs):
            delayedTaskFn = dask.delayed(mergedTaskAndCleanupFn)
            delayedResult = delayedTaskFn(*args, **kwargs)
            # @warning relying on resources imply we setup available resources
            # on every worker, including those setup through dask LocalCluster
            # or MPI, otherwise task scheduling will get stuck.
            future = client.compute(delayedResult, resources={'job': 1})
            taskResult = future.result()
            print(taskResult)

            return taskResult

        # Run task.
        # @note We don't provide the cleanup function here, cf.
        # mergedTaskAndCleanupFn's comment.
        return super().runTask(taskName, blockingTaskFn, None, *args, **kwargs)

    def batchTask(self, taskName: str, taskFn, cleanupFn, itemIds: Set[any]):
        client = self._client
        cache = self._history

        print(f'Batch {taskName} {str(itemIds)} starting.')

        # Merge task and cleanup together in order to execute the cleanup
        # within the worker node.
        def mergedTaskAndCleanupFn(*args, **kwargs):
            result = taskFn(*args, **kwargs)
            ignoredResult = cleanupFn(result.didSucceed, *args, **kwargs)
            return result

        # Gather task batch.
        delayedTaskFn = dask.delayed(mergedTaskAndCleanupFn)
        delayedResults = {}

        for itemId in itemIds:
            # Expand list itemId as argument for the function.
            if isinstance(itemId, collections.Sequence) and not \
               isinstance(itemId, str):
                didSucceedDelayed = delayedTaskFn(*itemId)
                delayedResults[itemId] = didSucceedDelayed
            # Expand dictionnary itemId as argument for the function.
            elif isinstance(itemId, dict):
                didSucceedDelayed = delayedTaskFn(**itemId)
                delayedResults[itemId] = didSucceedDelayed
            # Send itemId as argument for the function.
            else:
                didSucceedDelayed = delayedTaskFn(itemId)
                delayedResults[itemId] = didSucceedDelayed

        # Compute batch.
        # @warning relying on resources imply we setup available resources
        # on every worker, including those setup through dask LocalCluster
        # or MPI, otherwise task scheduling will get stuck.
        computations = client.compute(delayedResults, resources={'job': 1})
        results = computations.result()

        # Generate a list of successful itemIds.
        successfulItemIds = [
            itemId
            for itemId, taskResult in results.items()
            if taskResult.didSucceed  # noqa: E712
        ]

        # Generate a list of unsuccessful itemIds.
        failedItemIds = [
            item for item in itemIds if item not in successfulItemIds
        ]

        # Update cache.
        for itemId, taskResult in results.items():
            taskItemName = f'{taskName}_{str(itemId)}'
            didSucceed = taskResult.didSucceed
            returnCode = taskResult.returnCode
            cache.writeTaskCache(taskItemName, didSucceed, returnCode)

        print(f'Batch {taskName} {str(successfulItemIds)} succeeded.')
        print(f'Batch {taskName} {str(failedItemIds)} failed.')

        return successfulItemIds, failedItemIds