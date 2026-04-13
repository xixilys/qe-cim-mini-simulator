#pragma once

#include <cstddef>
#include <cstdint>

#if defined(QE_BAND_SOLVER_USE_SYSTEMC) && QE_BAND_SOLVER_USE_SYSTEMC
#include <tlm>
#else
namespace tlm {

enum tlm_command {
  TLM_READ_COMMAND,
  TLM_WRITE_COMMAND,
  TLM_IGNORE_COMMAND,
};

enum tlm_response_status {
  TLM_INCOMPLETE_RESPONSE,
  TLM_OK_RESPONSE,
  TLM_GENERIC_ERROR_RESPONSE,
};

class tlm_generic_payload {
 public:
  tlm_generic_payload() = default;

  void set_command(tlm_command command) { command_ = command; }
  tlm_command get_command() const { return command_; }

  void set_address(std::uint64_t address) { address_ = address; }
  std::uint64_t get_address() const { return address_; }

  void set_data_ptr(unsigned char* data_ptr) { data_ptr_ = data_ptr; }
  unsigned char* get_data_ptr() const { return data_ptr_; }

  void set_data_length(unsigned int data_length) { data_length_ = data_length; }
  unsigned int get_data_length() const { return data_length_; }

  void set_streaming_width(unsigned int streaming_width) {
    streaming_width_ = streaming_width;
  }
  unsigned int get_streaming_width() const { return streaming_width_; }

  void set_response_status(tlm_response_status response_status) {
    response_status_ = response_status;
  }
  tlm_response_status get_response_status() const { return response_status_; }

 private:
  tlm_command command_ = TLM_IGNORE_COMMAND;
  std::uint64_t address_ = 0;
  unsigned char* data_ptr_ = nullptr;
  unsigned int data_length_ = 0;
  unsigned int streaming_width_ = 0;
  tlm_response_status response_status_ = TLM_INCOMPLETE_RESPONSE;
};

}  // namespace tlm
#endif
