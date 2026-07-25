#include "sample_queue.hpp"

#include <chrono>
#include <cstddef>
#include <future>
#include <stdexcept>

#include <gtest/gtest.h>

namespace pynetft::bindings {

struct SampleQueueTestAccess {
  static bool wait_until_blocked(SampleQueue &queue, const std::size_t count,
                                 const std::chrono::duration<double> timeout) {
    std::unique_lock<std::mutex> lock(queue.mutex_);
    return queue.waiter_observed_condition_.wait_for(
        lock, timeout,
        [&queue, count] { return queue.waiting_reader_count_ >= count; });
  }

  static bool wait_until_woken(SampleQueue &queue, const std::size_t count,
                               const std::chrono::duration<double> timeout) {
    std::unique_lock<std::mutex> lock(queue.mutex_);
    return queue.woken_reader_condition_.wait_for(
        lock, timeout,
        [&queue, count] { return queue.woken_reader_count_ >= count; });
  }

  static void pause_woken_readers(SampleQueue &queue) {
    std::lock_guard<std::mutex> lock(queue.mutex_);
    queue.pause_woken_readers_ = true;
  }

  static void resume_woken_readers(SampleQueue &queue) {
    {
      std::lock_guard<std::mutex> lock(queue.mutex_);
      queue.pause_woken_readers_ = false;
    }
    queue.test_control_condition_.notify_all();
  }

  static void wake_readers_for_cleanup(SampleQueue &queue) {
    queue.condition_.notify_all();
  }
};

} // namespace pynetft::bindings

using namespace std::chrono_literals;
using pynetft::bindings::ReadStatus;
using pynetft::bindings::SampleQueue;
using pynetft::bindings::SampleQueueTestAccess;

TEST(SampleQueue, KeepsLatestSampleAtCapacity) {
  SampleQueue queue{1};
  netft::Sample first;
  first.rdt_sequence = 1;
  netft::Sample second;
  second.rdt_sequence = 2;
  queue.push(first);
  queue.push(second);

  const auto result = queue.read_for(1ms);
  ASSERT_EQ(result.status, ReadStatus::Sample);
  ASSERT_TRUE(result.sample);
  const auto sample = result.sample.value_or(netft::Sample{});
  EXPECT_EQ(sample.rdt_sequence, 2U);
  EXPECT_EQ(queue.dropped_count(), 1U);
}

TEST(SampleQueue, CloseWakesBlockedReader) {
  SampleQueue queue{1};
  auto future =
      std::async(std::launch::async, [&] { return queue.read_for(10s); });
  ASSERT_TRUE(SampleQueueTestAccess::wait_until_blocked(queue, 1, 1s));

  queue.close();

  const auto status = future.wait_for(1s);
  if (status != std::future_status::ready) {
    SampleQueueTestAccess::wake_readers_for_cleanup(queue);
  }
  EXPECT_EQ(status, std::future_status::ready);
  EXPECT_EQ(future.get().status, ReadStatus::Closed);
}

TEST(SampleQueue, TimeoutIsDistinctFromClose) {
  SampleQueue queue{1};
  EXPECT_EQ(queue.read_for(1ms).status, ReadStatus::Timeout);
}

TEST(SampleQueue, RejectsZeroCapacity) {
  EXPECT_THROW(SampleQueue{0}, std::invalid_argument);
}

TEST(SampleQueue, PopsSamplesInFifoOrder) {
  SampleQueue queue{2};
  netft::Sample first;
  first.rdt_sequence = 1;
  netft::Sample second;
  second.rdt_sequence = 2;
  queue.push(first);
  queue.push(second);

  const auto first_result = queue.read_for(1ms);
  const auto second_result = queue.read_for(1ms);

  ASSERT_EQ(first_result.status, ReadStatus::Sample);
  ASSERT_TRUE(first_result.sample);
  const auto first_sample = first_result.sample.value_or(netft::Sample{});
  EXPECT_EQ(first_sample.rdt_sequence, 1U);
  ASSERT_EQ(second_result.status, ReadStatus::Sample);
  ASSERT_TRUE(second_result.sample);
  const auto second_sample = second_result.sample.value_or(netft::Sample{});
  EXPECT_EQ(second_sample.rdt_sequence, 2U);
}

TEST(SampleQueue, CloseWakesAllBlockedReaders) {
  SampleQueue queue{1};
  auto first =
      std::async(std::launch::async, [&] { return queue.read_for(10s); });
  auto second =
      std::async(std::launch::async, [&] { return queue.read_for(10s); });
  ASSERT_TRUE(SampleQueueTestAccess::wait_until_blocked(queue, 2, 1s));

  queue.close();

  const auto first_status = first.wait_for(1s);
  const auto second_status = second.wait_for(1s);
  if (first_status != std::future_status::ready ||
      second_status != std::future_status::ready) {
    SampleQueueTestAccess::wake_readers_for_cleanup(queue);
  }
  EXPECT_EQ(first_status, std::future_status::ready);
  EXPECT_EQ(second_status, std::future_status::ready);
  EXPECT_EQ(first.get().status, ReadStatus::Closed);
  EXPECT_EQ(second.get().status, ReadStatus::Closed);
}

TEST(SampleQueue, BlockedReaderObservesCloseAcrossImmediateReset) {
  SampleQueue queue{1};
  auto future =
      std::async(std::launch::async, [&] { return queue.read_for(10s); });
  ASSERT_TRUE(SampleQueueTestAccess::wait_until_blocked(queue, 1, 1s));
  SampleQueueTestAccess::pause_woken_readers(queue);

  queue.close();
  const auto woke_from_close =
      SampleQueueTestAccess::wait_until_woken(queue, 1, 1s);
  if (!woke_from_close) {
    SampleQueueTestAccess::wake_readers_for_cleanup(queue);
  }
  EXPECT_TRUE(woke_from_close);

  queue.reset();
  netft::Sample sample;
  queue.push(sample);
  SampleQueueTestAccess::resume_woken_readers(queue);

  EXPECT_EQ(future.get().status, ReadStatus::Closed);
}

TEST(SampleQueue, CloseHasPriorityOverQueuedSamples) {
  SampleQueue queue{1};
  netft::Sample sample;
  queue.push(sample);

  queue.close();

  const auto result = queue.read_for(1ms);
  EXPECT_EQ(result.status, ReadStatus::Closed);
  EXPECT_FALSE(result.sample);
}

TEST(SampleQueue, ResetClearsReopensAndResetsDroppedCount) {
  SampleQueue queue{1};
  netft::Sample first;
  first.rdt_sequence = 1;
  netft::Sample second;
  second.rdt_sequence = 2;
  queue.push(first);
  queue.push(second);
  queue.close();

  queue.reset();

  EXPECT_EQ(queue.dropped_count(), 0U);
  EXPECT_EQ(queue.read_for(1ms).status, ReadStatus::Timeout);

  queue.push(first);
  const auto result = queue.read_for(1ms);
  ASSERT_EQ(result.status, ReadStatus::Sample);
  ASSERT_TRUE(result.sample);
  const auto sample = result.sample.value_or(netft::Sample{});
  EXPECT_EQ(sample.rdt_sequence, 1U);
}

TEST(SampleQueue, PreservesFifoOrderUnderConcurrentUse) {
  constexpr std::uint32_t sample_count = 1000;
  SampleQueue queue{sample_count};
  auto producer = std::async(std::launch::async, [&] {
    for (std::uint32_t sequence = 0; sequence < sample_count; ++sequence) {
      netft::Sample sample;
      sample.rdt_sequence = sequence;
      queue.push(sample);
    }
  });

  for (std::uint32_t sequence = 0; sequence < sample_count; ++sequence) {
    const auto result = queue.read_for(1s);
    ASSERT_EQ(result.status, ReadStatus::Sample);
    ASSERT_TRUE(result.sample);
    const auto sample = result.sample.value_or(netft::Sample{});
    EXPECT_EQ(sample.rdt_sequence, sequence);
  }
  producer.get();
  EXPECT_EQ(queue.dropped_count(), 0U);
}
