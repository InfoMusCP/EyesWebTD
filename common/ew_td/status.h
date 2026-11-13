// Why a cook produced (or did not produce) output. Mirrors pyeyesweb.data_models.Status: same names, same integers,
// so a status read from a CHOP and one read from PyEyesWeb are comparable.
#pragma once
#include <stdexcept>
#include <string>

namespace ew_td {

enum class Status : int {
    Ok = 0,            // the cook produced output
    WarmingUp = 1,     // a window or internal state is still filling
    NoOutput = 2,      // the feature emits only on some cooks and this was not one of them
    InvalidInput = 3,  // the input is not data (empty, too short, wrong channel count, NaN); the reason says why
};

inline const char* statusName(Status s) {
    switch (s) {
        case Status::Ok: return "OK";
        case Status::WarmingUp: return "WARMING_UP";
        case Status::NoOutput: return "NO_OUTPUT";
        case Status::InvalidInput: return "INVALID_INPUT";
    }
    return "?";
}

// Thrown by a cook (or by the input readers) for an input that cannot be processed. The base class turns it into
// Status::InvalidInput with the message as the reason, and the outputs stay zero.
struct InputError : std::runtime_error {
    using std::runtime_error::runtime_error;
};

// require(cond, "message"): the one-line input check of a cook.
inline void require(bool condition, const char* message) {
    if (!condition) throw InputError(message);
}
inline void require(bool condition, const std::string& message) {
    if (!condition) throw InputError(message);
}

}  // namespace ew_td
