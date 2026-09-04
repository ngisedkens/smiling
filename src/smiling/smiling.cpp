#include <cstddef>
#include <cstdint>
#include <cstring>
#include <memory>
#include <string>
#include <vector>

#include <nanobind/nanobind.h>
#include <nanobind/stl/vector.h>
#include <nanobind/stl/wstring.h>
#include <Python.h>

extern "C" {
#include <libavutil/aes.h>
}

#ifndef UNICODE
#  define UNICODE
#endif
#ifndef WIN32_LEAN_AND_MEAN
#  define WIN32_LEAN_AND_MEAN
#endif
#include <Windows.h>

namespace {
class Overwritten {
  public:
    Overwritten(const char *iv, const char *key);

    auto a() { return reinterpret_cast<AVAES *>(a_); }

    uint8_t iv_[16];

  private:
    std::byte a_[288];
};
}  // namespace

Overwritten::Overwritten(const char *iv, const char *key) {
    if (av_aes_init(
        a(),
        reinterpret_cast<const uint8_t *>(key),
        /*key_bits=*/128,
        /*decrypt=*/1
    )) [[unlikely]] {
        throw nanobind::buffer_error("av_aes_init failed");
    }

    // Compiled to `vmovups` when `x86_64-microarch-level >=3`
    std::memcpy(iv_, iv, 16);
}

NB_MODULE(_smiling, m) {
    SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);

    m.def(
        "m3u8_concat",
        [](
            const nanobind::bytes &iv,
            const nanobind::bytes &header,
            const nanobind::bytes &key,
            const std::vector<nanobind::bytes> &segments
        ) {
            Overwritten data {
                PyBytes_AS_STRING(iv.ptr()),
                PyBytes_AS_STRING(key.ptr()),
            };
            size_t header_size = PyBytes_GET_SIZE(header.ptr());
            size_t n = header_size;
            for (const auto &segment : segments) {
                size_t i = PyBytes_GET_SIZE(segment.ptr());
                if (i % 16) [[unlikely]] {
                    throw nanobind::value_error("Bad segment size");
                }
                n += i;
            }
            auto s = std::make_unique_for_overwrite<uint8_t[]>(n);
            std::memcpy(s.get(), PyBytes_AS_STRING(header.ptr()), header_size);
            uint8_t *input = &s[header_size];
            for (const auto &segment : segments) {
                auto obj = segment.ptr();
                size_t i = PyBytes_GET_SIZE(obj);
                std::memcpy(input, PyBytes_AS_STRING(obj), i);
                auto overwritten = data;
                av_aes_crypt(
                    overwritten.a(),
                    /*dst=*/input,
                    /*src=*/input,
                    /*count=*/i / 16,
                    overwritten.iv_,
                    /*decrypt=*/1
                );
                input += i - input[i-1];
            }
            return nanobind::bytes {
                s.get(),
                static_cast<size_t>(input - s.get()),
            };
        }
    );

    m.def(
        "message_box",
        [](const std::wstring &title, const nanobind::bytes &body) {
            MessageBox(
                nullptr,
                reinterpret_cast<LPCWSTR>(PyBytes_AS_STRING(body.ptr())),
                title.c_str(),
                MB_OK
            );
        }
    );
}
