// TouchDesigner Symmetry CHOP - wraps ew::motion::GeometricSymmetry (PyEyesWeb Symmetry, method "reflection")
// Input: channels structured as joint-major (j0_x, j0_y, j0_z, j1_x, ...), with parameter Dims.
// Parameters: Left/Right joint pairs ("0,1 2,3"), Center joint of symmetry (-1 for barycenter).
// Output: one channel per pair, pair_symmetry_<left>_<right>, the symmetry score in [0, 1], one sample per input sample.
#include <set>
#include <sstream>
#include <string>
#include <vector>
#include <cstring>
#include "ew/features/motion/symmetry.h"
#include "ew/features/motion/symmetry_index_3d.h"
#include "ew_td/plugin.h"

using namespace TD;
using namespace ew_td;
using ew::motion::GeometricSymmetry;
using ew::motion::SymmetryIndex3D;

namespace {
// The pairs of the Pairs parameter; a token that is not "a,b" is skipped, and (0, 1) when none is left; sorted, without duplicates (as the core).
std::vector<GeometricSymmetry::Pair> parsePairs(const OP_Inputs* in) {
    std::set<GeometricSymmetry::Pair> result;
    const char* str = in->getParString("Pairs");
    if (!str) return {};
    std::stringstream ss(str);
    std::string token;
    while (ss >> token) {
        const size_t comma = token.find(',');
        if (comma == std::string::npos) continue;
        try {
            const int a = std::stoi(token.substr(0, comma));
            const int b = std::stoi(token.substr(comma + 1));
            result.insert({a, b});
        } catch (const std::exception&) {
        }
    }
    if (result.empty()) result.insert({0, 1});
    return {result.begin(), result.end()};
}
}  // namespace

class SymmetryCHOP : public EwChop {
public:
    explicit SymmetryCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs* in) const override {
        Schema schema;
        if (isRatio(in)) {  // the EyesWeb index of named couples: one value, or one per axis
            if (in->getParInt("Components") != 0) {
                schema.add(Output::scalar("symmetry_x"));
                schema.add(Output::scalar("symmetry_y"));
                schema.add(Output::scalar("symmetry_z"));
            } else {
                schema.add(Output::scalar("symmetry"));
            }
            return schema;
        }
        for (const auto& pair : parsePairs(in))
            schema.add(Output::scalar("pair_symmetry_" + std::to_string(pair.first) + "_" + std::to_string(pair.second)));
        if (schema.size() == 0) schema.add(Output::scalar("symm0"));
        return schema;
    }

    int numSamples(const OP_Inputs* in) const override { return inputSamples(in); }

    void declareParameters(Params& p) override {
        p.page("Symmetry");
        p.menu("Method", "Method", "reflection", {{"reflection", "Reflection (score per pair)"}, {"ratio", "Ratio (EyesWeb index)"}});
        p.menu("Aggregation", "Aggregation (ratio)", "mean",
               {{"mean", "Mean"}, {"min", "Min"}, {"max", "Max"}, {"weighted_mean", "Weighted Mean"}});
        p.menu("Indextype", "Index Type (ratio)", "symmetry", {{"symmetry", "Symmetry"}, {"symmetry_asymmetry", "Symmetry Asymmetry"}});
        p.toggle("Components", "One Value per Axis (ratio)", false);
        p.toggle("Normalizeskeleton", "Normalize Skeleton (ratio)", true);
        p.integer("Dims", "Dims", 3, Range::atLeast(1, 4));
        p.string("Pairs", "Joint Pairs (e.g. 0,1 2,3)", "0,1");
        p.integer("Referencepoint", "Reference Point (joint, -1 = barycenter)", -1, Range::atLeast(-1, 50));
    }

    void cook(CHOP_Output* out, const OP_Inputs* in) override {
        const InputView input = chopInput(in);
        requireFinite(input);
        int dims = in->getParInt("Dims");
        if (dims < 1) dims = 1;
        const int joints = jointCount(input, dims);

        if (isRatio(in)) {
            require(dims == 3, "The ratio method needs Dims = 3");
            SymmetryIndex3D::Params rp;
            const int reference = in->getParInt("Referencepoint");
            require(reference >= 0 && reference < joints, "The ratio method needs a Reference Point among the joints");
            for (const auto& pair : parsePairs(in))
                require(pair.first >= 0 && pair.first < joints && pair.second >= 0 && pair.second < joints,
                        "A joint pair names a joint that is not in the input");
            labels_[joints - 1];  // create every label first: a later call could reallocate and invalidate a reference
            for (const auto& pair : parsePairs(in)) rp.pairs.push_back({labels_[pair.first], labels_[pair.second]});
            rp.referenceType = SymmetryIndex3D::ReferenceType::Label;
            rp.referencePoint = labels_[reference];
            const char* aggregation = in->getParString("Aggregation");
            rp.aggregation = !std::strcmp(aggregation, "min")   ? SymmetryIndex3D::Algorithm::Min
                             : !std::strcmp(aggregation, "max") ? SymmetryIndex3D::Algorithm::Max
                             : !std::strcmp(aggregation, "weighted_mean") ? SymmetryIndex3D::Algorithm::WeightedMean
                                                                          : SymmetryIndex3D::Algorithm::Mean;
            rp.indexType = std::strcmp(in->getParString("Indextype"), "symmetry_asymmetry") == 0
                               ? SymmetryIndex3D::IndexType::SymmetryAsymmetry : SymmetryIndex3D::IndexType::Symmetry;
            const bool components = in->getParInt("Components") != 0;
            rp.outputDims = components ? SymmetryIndex3D::OutputType::Components : SymmetryIndex3D::OutputType::Global;
            rp.normalizeSkeleton = in->getParInt("Normalizeskeleton") != 0;
            const SymmetryIndex3D index(rp);
            for (int s = 0; s < out->numSamples; ++s) {
                const SymmetryIndex3D::Result result = index.process(readFrame(input, dims, s, labels_));
                if (components) {
                    out->channels[0][s] = static_cast<float>(result.components.x);
                    out->channels[1][s] = static_cast<float>(result.components.y);
                    out->channels[2][s] = static_cast<float>(result.components.z);
                } else {
                    out->channels[0][s] = static_cast<float>(result.global);
                }
            }
            return;
        }

        GeometricSymmetry::Params p;
        p.pairs = parsePairs(in);
        p.referencePoint = in->getParInt("Referencepoint");
        const GeometricSymmetry symmetry(p);

        ew::Matrix frame(joints, dims);
        for (int s = 0; s < out->numSamples; ++s) {
            for (int j = 0; j < joints; ++j)
                for (int d = 0; d < dims; ++d) frame(j, d) = input.at(j * dims + d, s);
            const std::vector<double> scores = symmetry.process(frame);
            for (size_t c = 0; c < scores.size() && static_cast<int>(c) < out->numChannels; ++c)
                out->channels[c][s] = static_cast<float>(scores[c]);
        }
    }

private:
    static bool isRatio(const OP_Inputs* in) { return std::strcmp(in->getParString("Method"), "ratio") == 0; }
    ew_td::JointLabels labels_;
};

EW_TD_CHOP(SymmetryCHOP, "Ewsymmetry", "EW L2 Symmetry", 1, 1)
