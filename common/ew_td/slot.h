// Holder of the core feature of an operator, for the cook-to-cook life of a feature whose parameters can change.
//   * the feature is built at the first use, with the parameters of that cook;
//   * at the next cooks the new parameters are handed to `adoptParams` (the contract of the core, see CONVENTIONS.md):
//     a structural change (a window length, a dimension) resets the state of the feature, a live one (a threshold)
//     does not, so turning a knob never silently keeps a state that belongs to other parameters;
//   * `drop` forgets the feature, and with it every bit of its state: the next use builds it afresh.
// Requires of Feature: a nested `Params`, a constructor from Params, and `bool adoptParams(const Feature& fresh)`.
// No TouchDesigner dependency.
#pragma once
#include <memory>

namespace ew_td {

template <class Feature>
class FeatureSlot {
public:
    using Params = typename Feature::Params;

    // The feature configured with `params`. Throws what the constructor of the feature throws for invalid parameters.
    Feature& get(const Params& params) {
        if (!feature_) {
            feature_ = std::make_unique<Feature>(params);
        } else {
            const Feature fresh(params);
            feature_->adoptParams(fresh);
        }
        return *feature_;
    }

    void drop() { feature_.reset(); }
    bool empty() const { return !feature_; }

private:
    std::unique_ptr<Feature> feature_;
};

}  // namespace ew_td
