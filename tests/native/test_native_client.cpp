#include "native_client.hpp"

#include <chrono>
#include <future>
#include <mutex>

#include <gtest/gtest.h>

namespace pynetft::bindings {

struct NativeClientTestAccess {
  static void pause_stop_before_core(NativeClient &client) {
    std::lock_guard<std::mutex> lock(client.test_mutex_);
    client.pause_before_core_stop_ = true;
    client.core_stop_observed_ = false;
  }

  static bool
  wait_until_core_stop_observed(NativeClient &client,
                                const std::chrono::duration<double> timeout) {
    std::unique_lock<std::mutex> lock(client.test_mutex_);
    return client.test_condition_.wait_for(
        lock, timeout, [&client] { return client.core_stop_observed_; });
  }

  static void resume_core_stop(NativeClient &client) {
    {
      std::lock_guard<std::mutex> lock(client.test_mutex_);
      client.pause_before_core_stop_ = false;
    }
    client.test_condition_.notify_all();
  }

  static void force_running_first_sample_gate(NativeClient &client) {
    client.running_.store(true, std::memory_order_release);
    client.forced_fault_.store(false, std::memory_order_release);
    std::lock_guard<std::mutex> lock(client.test_mutex_);
    client.gate_first_sample_calls_ = true;
    client.first_sample_call_count_ = 0;
    client.first_sample_calls_allowed_ = 0;
  }

  static bool
  wait_until_first_sample_calls(NativeClient &client, const std::uint64_t count,
                                const std::chrono::duration<double> timeout) {
    std::unique_lock<std::mutex> lock(client.test_mutex_);
    return client.test_condition_.wait_for(lock, timeout, [&client, count] {
      return client.first_sample_call_count_ >= count;
    });
  }

  static void allow_first_sample_calls(NativeClient &client,
                                       const std::uint64_t count) {
    {
      std::lock_guard<std::mutex> lock(client.test_mutex_);
      client.first_sample_calls_allowed_ = count;
    }
    client.test_condition_.notify_all();
  }

  static void disable_first_sample_gate(NativeClient &client) {
    {
      std::lock_guard<std::mutex> lock(client.test_mutex_);
      client.gate_first_sample_calls_ = false;
    }
    client.test_condition_.notify_all();
  }

  static std::uint64_t first_sample_call_count(NativeClient &client) {
    std::lock_guard<std::mutex> lock(client.test_mutex_);
    return client.first_sample_call_count_;
  }

  static void force_running_timeout_pause(NativeClient &client) {
    client.running_.store(true, std::memory_order_release);
    client.forced_fault_.store(false, std::memory_order_release);
    std::lock_guard<std::mutex> lock(client.test_mutex_);
    client.pause_after_timeout_ = true;
    client.timeout_observed_ = false;
  }

  static bool
  wait_until_timeout_observed(NativeClient &client,
                              const std::chrono::duration<double> timeout) {
    std::unique_lock<std::mutex> lock(client.test_mutex_);
    return client.test_condition_.wait_for(
        lock, timeout, [&client] { return client.timeout_observed_; });
  }

  static void resume_timed_out_read(NativeClient &client) {
    {
      std::lock_guard<std::mutex> lock(client.test_mutex_);
      client.pause_after_timeout_ = false;
    }
    client.test_condition_.notify_all();
  }

  static void force_running_fault(NativeClient &client) {
    client.running_.store(true, std::memory_order_release);
    client.forced_fault_.store(true, std::memory_order_release);
    std::lock_guard<std::mutex> lock(client.test_mutex_);
    client.pause_after_fault_ = true;
    client.fault_observed_ = false;
  }

  static bool
  wait_until_fault_observed(NativeClient &client,
                            const std::chrono::duration<double> timeout) {
    std::unique_lock<std::mutex> lock(client.test_mutex_);
    return client.test_condition_.wait_for(
        lock, timeout, [&client] { return client.fault_observed_; });
  }

  static void simulate_restart(NativeClient &client) {
    client.running_.store(false, std::memory_order_release);
    client.queue_.close();
    client.queue_.reset();
    client.forced_fault_.store(false, std::memory_order_release);
    client.running_.store(true, std::memory_order_release);
  }

  static void resume_faulted_read(NativeClient &client) {
    {
      std::lock_guard<std::mutex> lock(client.test_mutex_);
      client.pause_after_fault_ = false;
    }
    client.test_condition_.notify_all();
  }

  static void push(NativeClient &client, const netft::Sample &sample) {
    client.queue_.push(sample);
  }

  static ReadResult read_queue(NativeClient &client,
                               const std::chrono::duration<double> timeout) {
    return client.queue_.read_for(timeout);
  }
};

} // namespace pynetft::bindings

using namespace std::chrono_literals;
using pynetft::bindings::NativeClient;
using pynetft::bindings::NativeClientTestAccess;
using pynetft::bindings::ReadStatus;

TEST(NativeClient, StaleFaultedReadDoesNotCloseRestartedQueue) {
  NativeClient client{netft::Config{}, 1};
  NativeClientTestAccess::force_running_fault(client);
  auto stale_read = std::async(std::launch::async,
                               [&client] { return client.read(std::nullopt); });
  const auto observed_fault =
      NativeClientTestAccess::wait_until_fault_observed(client, 1s);
  if (!observed_fault) {
    NativeClientTestAccess::resume_faulted_read(client);
    client.stop();
  }
  ASSERT_TRUE(observed_fault);

  NativeClientTestAccess::simulate_restart(client);
  NativeClientTestAccess::resume_faulted_read(client);

  const auto stale_status = stale_read.wait_for(1s);
  if (stale_status != std::future_status::ready) {
    client.stop();
  }
  ASSERT_EQ(stale_status, std::future_status::ready);
  ASSERT_EQ(stale_read.get().status, ReadStatus::Closed);
  netft::Sample sample;
  sample.rdt_sequence = 42;
  NativeClientTestAccess::push(client, sample);
  const auto restarted_result = NativeClientTestAccess::read_queue(client, 1ms);
  ASSERT_EQ(restarted_result.status, ReadStatus::Sample);
  ASSERT_TRUE(restarted_result.sample);
  const auto restarted_sample =
      restarted_result.sample.value_or(netft::Sample{});
  EXPECT_EQ(restarted_sample.rdt_sequence, 42U);
}

TEST(NativeClient, LogicalReadDoesNotCrossACompleteRestartBetweenSlices) {
  NativeClient client{netft::Config{}, 1};
  NativeClientTestAccess::force_running_timeout_pause(client);
  auto stale_read = std::async(std::launch::async,
                               [&client] { return client.read(std::nullopt); });
  const auto observed_timeout =
      NativeClientTestAccess::wait_until_timeout_observed(client, 1s);
  if (!observed_timeout) {
    NativeClientTestAccess::resume_timed_out_read(client);
    client.stop();
  }
  ASSERT_TRUE(observed_timeout);

  NativeClientTestAccess::simulate_restart(client);
  netft::Sample new_run_sample;
  new_run_sample.rdt_sequence = 84;
  NativeClientTestAccess::push(client, new_run_sample);
  NativeClientTestAccess::resume_timed_out_read(client);

  const auto stale_status = stale_read.wait_for(1s);
  if (stale_status != std::future_status::ready) {
    client.stop();
  }
  ASSERT_EQ(stale_status, std::future_status::ready);
  ASSERT_EQ(stale_read.get().status, ReadStatus::Closed);
  const auto new_read = NativeClientTestAccess::read_queue(client, 1ms);
  ASSERT_EQ(new_read.status, ReadStatus::Sample);
  ASSERT_TRUE(new_read.sample);
  const auto new_sample = new_read.sample.value_or(netft::Sample{});
  EXPECT_EQ(new_sample.rdt_sequence, 84U);
}

TEST(NativeClient, FirstSampleWaitStopsBeforeBlockedCoreJoinWithoutRepeating) {
  NativeClient client{netft::Config{}, 1};
  NativeClientTestAccess::force_running_first_sample_gate(client);
  NativeClientTestAccess::pause_stop_before_core(client);
  auto waiter = std::async(std::launch::async, [&client] {
    return client.wait_for_first_sample(10.0);
  });
  const auto observed_first_call =
      NativeClientTestAccess::wait_until_first_sample_calls(client, 1, 1s);
  if (!observed_first_call) {
    NativeClientTestAccess::disable_first_sample_gate(client);
    NativeClientTestAccess::resume_core_stop(client);
    client.stop();
  }
  ASSERT_TRUE(observed_first_call);
  auto stopper = std::async(std::launch::async, [&client] { client.stop(); });
  const auto observed_core_stop =
      NativeClientTestAccess::wait_until_core_stop_observed(client, 1s);
  if (!observed_core_stop) {
    NativeClientTestAccess::disable_first_sample_gate(client);
    NativeClientTestAccess::resume_core_stop(client);
    stopper.get();
    static_cast<void>(waiter.get());
  }
  ASSERT_TRUE(observed_core_stop);

  NativeClientTestAccess::allow_first_sample_calls(client, 1);
  const auto waiter_status = waiter.wait_for(1s);
  const auto stop_status = stopper.wait_for(0ms);
  const auto call_count =
      NativeClientTestAccess::first_sample_call_count(client);

  NativeClientTestAccess::resume_core_stop(client);
  stopper.get();
  NativeClientTestAccess::disable_first_sample_gate(client);
  EXPECT_FALSE(waiter.get());

  EXPECT_EQ(waiter_status, std::future_status::ready);
  EXPECT_EQ(stop_status, std::future_status::timeout);
  EXPECT_EQ(call_count, 1U);
}

TEST(NativeClient, ReadClosesBeforeBlockedCoreJoinCompletes) {
  NativeClient client{netft::Config{}, 1};
  NativeClientTestAccess::force_running_timeout_pause(client);
  NativeClientTestAccess::pause_stop_before_core(client);
  auto reader = std::async(std::launch::async,
                           [&client] { return client.read(std::nullopt); });
  const auto observed_timeout =
      NativeClientTestAccess::wait_until_timeout_observed(client, 1s);
  if (!observed_timeout) {
    NativeClientTestAccess::resume_timed_out_read(client);
    NativeClientTestAccess::resume_core_stop(client);
    client.stop();
  }
  ASSERT_TRUE(observed_timeout);
  auto stopper = std::async(std::launch::async, [&client] { client.stop(); });
  const auto observed_core_stop =
      NativeClientTestAccess::wait_until_core_stop_observed(client, 1s);
  if (!observed_core_stop) {
    NativeClientTestAccess::resume_timed_out_read(client);
    NativeClientTestAccess::resume_core_stop(client);
    stopper.get();
    static_cast<void>(reader.get());
  }
  ASSERT_TRUE(observed_core_stop);

  NativeClientTestAccess::resume_timed_out_read(client);
  const auto reader_status = reader.wait_for(1s);
  const auto stop_status = stopper.wait_for(0ms);

  NativeClientTestAccess::resume_core_stop(client);
  stopper.get();
  EXPECT_EQ(reader.get().status, ReadStatus::Closed);

  EXPECT_EQ(reader_status, std::future_status::ready);
  EXPECT_EQ(stop_status, std::future_status::timeout);
}
