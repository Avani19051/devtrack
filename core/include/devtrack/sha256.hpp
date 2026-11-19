// SHA-256 hashing used for content-addressed artifact storage.
#pragma once
#include <cstdint>
#include <string>
#include <vector>

namespace devtrack {

class Sha256 {
public:
    Sha256();
    void update(const uint8_t* data, size_t len);
    void update(const std::string& s);
    std::string hexdigest();  // finalizes; call once

private:
    void transform(const uint8_t block[64]);
    uint32_t state_[8];
    uint8_t buffer_[64];
    uint64_t bitlen_;
    size_t buflen_;
    bool finalized_;
};

std::string sha256_string(const std::string& data);
// Hashes a file in chunks. Throws std::runtime_error if the file can't be read.
std::string sha256_file(const std::string& path);

}  // namespace devtrack
