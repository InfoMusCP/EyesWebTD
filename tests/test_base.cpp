// Tests of the parts of the base layer that do not need TouchDesigner: schema flat names, joint labels, status,
// the feature slot, the reset rules of a streaming operator, the Info entries.
// Expected names are the ones PyEyesWeb gives the same outputs (pyeyesweb.data_models.Output.flat_names).
#include <cstdio>
#include <string>
#include <vector>
#include "ew_td/info.h"
#include "ew_td/labels.h"
#include "ew_td/schema.h"
#include "ew_td/slot.h"
#include "ew_td/status.h"
#include "ew_td/stream_state.h"

static int failures = 0;

#define CHECK(condition)                                                              \
    do {                                                                              \
        if (!(condition)) {                                                           \
            std::printf("FAILED line %d: %s\n", __LINE__, #condition);                \
            ++failures;                                                               \
        }                                                                             \
    } while (0)

using ew_td::Output;
using ew_td::Schema;
using Names = std::vector<std::string>;

// A feature as the core writes them: Params, a constructor from Params, adoptParams (a structural change resets).
struct MockFeature {
    struct Params {
        int window = 5;
        double threshold = 1.0;
    };
    explicit MockFeature(Params p) : params(p) {}
    bool adoptParams(const MockFeature& fresh) {
        const bool structural = params.window != fresh.params.window;
        params = fresh.params;
        if (structural) state = 0;
        return structural;
    }
    Params params;
    int state = 0;
};

int main() {
    CHECK(Output::scalar("directness_index").flatNames() == Names{"directness_index"});
    CHECK(Output::vector("position", {"x", "y", "z"}).flatNames() == (Names{"position_x", "position_y", "position_z"}));
    CHECK(Output::indexed("count", 3).flatNames() == (Names{"count_0", "count_1", "count_2"}));
    CHECK(Output::grid("energy", {"head", "hand"}, {"x", "y"}).flatNames() ==
          (Names{"energy_head_x", "energy_head_y", "energy_hand_x", "energy_hand_y"}));

    Schema schema{Output::scalar("total"), Output::vector("axis", {"x", "y"})};
    CHECK(schema.flatNames() == (Names{"total", "axis_x", "axis_y"}));
    CHECK(schema.size() == 3);
    CHECK(Schema{}.size() == 0);

    ew_td::JointLabels labels;
    CHECK(labels[0] == "0");
    CHECK(labels[11] == "11");
    CHECK(labels[2] == "2");

    CHECK(static_cast<int>(ew_td::Status::Ok) == 0 && static_cast<int>(ew_td::Status::WarmingUp) == 1);
    CHECK(static_cast<int>(ew_td::Status::NoOutput) == 2 && static_cast<int>(ew_td::Status::InvalidInput) == 3);
    CHECK(std::string(ew_td::statusName(ew_td::Status::InvalidInput)) == "INVALID_INPUT");

    bool thrown = false;
    try {
        ew_td::require(false, "bad input");
    } catch (const ew_td::InputError& e) {
        thrown = std::string(e.what()) == "bad input";
    }
    CHECK(thrown);
    ew_td::require(true, "never thrown");

    // FeatureSlot: built once; a live parameter keeps the state, a structural one resets it; drop forgets everything.
    {
        ew_td::FeatureSlot<MockFeature> slot;
        CHECK(slot.empty());
        MockFeature::Params p;
        MockFeature& first = slot.get(p);
        first.state = 7;
        p.threshold = 2.0;
        MockFeature& live = slot.get(p);
        CHECK(&live == &first && live.state == 7 && live.params.threshold == 2.0);
        p.window = 9;
        MockFeature& structural = slot.get(p);
        CHECK(structural.state == 0 && structural.params.window == 9);
        structural.state = 3;
        slot.drop();
        CHECK(slot.empty() && slot.get(p).state == 0);
    }

    // StreamState: when the state is dropped.
    {
        using ew_td::ResetReason;
        ew_td::StreamState state;
        const ew_td::InputSignature a{6, 60.0}, b{9, 60.0}, c{6, 120.0};
        CHECK(state.begin(a, false) == ResetReason::First);
        state.processed(10);
        CHECK(state.begin(a, false) == ResetReason::None);
        state.processed(5);
        CHECK(state.samplesProcessed() == 15 && state.resets() == 0);
        state.requestReset();
        CHECK(state.begin(a, false) == ResetReason::Requested);
        CHECK(state.samplesProcessed() == 0 && state.resets() == 1);
        state.processed(4);
        CHECK(state.begin(b, false) == ResetReason::InputChanged && state.resets() == 2);
        CHECK(state.begin(c, false) == ResetReason::InputChanged && state.resets() == 3);
        CHECK(state.begin(c, true) == ResetReason::Clip);
        CHECK(state.begin(c, true) == ResetReason::Clip && state.resets() == 3);  // a clip is not counted as a reset
        state.processed(8);
        CHECK(state.begin(c, true) == ResetReason::Clip && state.samplesProcessed() == 0);
        CHECK(state.begin(c, false) == ResetReason::None);
        state.requestReset();
        CHECK(state.begin(c, true) == ResetReason::Requested);  // a request wins over the clip
        CHECK(!(a != a));
    }

    // Info: numeric entries are channels, every entry is a row.
    {
        ew_td::Info info;
        info.number("status", 0, "OK");
        info.text("reason", "");
        info.number("samples", 4);
        CHECK(info.entries().size() == 3 && info.numericCount() == 2);
        CHECK(info.numericAt(1).name == "samples" && info.numericAt(1).text == "4");
        CHECK(info.entries()[0].text == "OK");
        info.clear();
        CHECK(info.entries().empty());
    }

    if (failures == 0) std::printf("ew_td base: all checks passed\n");
    return failures == 0 ? 0 : 1;
}
