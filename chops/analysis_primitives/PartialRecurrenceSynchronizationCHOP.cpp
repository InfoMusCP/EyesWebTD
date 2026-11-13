// TouchDesigner Partial Recurrence Synchronization CHOP - wraps ew::sync::PARS
// Partial recurrence synchronization matrix from a square CPR matrix (its inverse, normalised).
// Input: N channels x N samples (the output of the Correlations Matrix CHOP).
// Output: N channels x N samples: channel i, sample j = synchronization(i, j) (channels named
// synchronization_matrix_<i>).
// Frame operator: the matrix to transform is the CHOP content, nothing is kept between cooks.
#include <cmath>
#include "ew/common/matrix.h"
#include "ew/features/sync/partial_recurrence_synchronization.h"
#include "ew_td/plugin.h"

using namespace TD;
using namespace ew_td;
using ew::Matrix;
using ew::sync::PARS;

class PartialRecurrenceSynchronizationCHOP : public EwChop {
public:
    explicit PartialRecurrenceSynchronizationCHOP(const OP_NodeInfo*) {}

    Schema schema(const OP_Inputs* in) const override { return {Output::indexed("synchronization_matrix", size(in))}; }
    int numSamples(const OP_Inputs* in) const override { return size(in); }

    void cook(CHOP_Output* out, const OP_Inputs* in) override {
        const InputView input = chopInput(in);
        requireFinite(input);
        const int n = input.channels();
        require(input.samples() >= n, "Input matrix must be square (samples >= channels)");

        Matrix cpr(n, n);
        for (int r = 0; r < n; ++r)
            for (int c = 0; c < n; ++c) cpr(r, c) = input.at(r, c);

        const PARS pars;
        const Matrix result = pars.process(cpr);
        for (int r = 0; r < n && r < out->numChannels; ++r)
            for (int c = 0; c < n && c < out->numSamples; ++c) out->channels[r][c] = static_cast<float>(result(r, c));
        // As PyEyesWeb: NaN everywhere = ill-conditioned (condition number above 1e12), NaN somewhere = not positive definite.
        bool anyNaN = false;
        for (double v : result.data) anyNaN = anyNaN || std::isnan(v);
        if (anyNaN && !(PARS::conditionNumber(cpr) <= PARS::kMaxCondition)) setStatus(Status::InvalidInput, "ill-conditioned matrix (condition number above 1e12)");
        else if (anyNaN) setStatus(Status::InvalidInput, "not positive definite: not a correlation matrix");
    }

private:
    static int size(const OP_Inputs* in) { return in->getNumInputs() ? in->getInputCHOP(0)->numChannels : 1; }
};

EW_TD_CHOP(PartialRecurrenceSynchronizationCHOP, "Ewpartialrecurrencesynchronization",
           "EW AP Partial Recurrence Synchronization", 1, 1)
