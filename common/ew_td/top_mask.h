// The silhouette of a TOP as an 8-bit mask, for the operators that read an image (Silhouette Centroids, Body Parts).
//
// The TOP named by the operator's `Top` parameter is downloaded as one 8-bit channel (a quarter of the bytes of a 32-bit
// float image, which is most of the time of an operator at video sizes) and used as it is: the downloaded bytes are the
// mask and nothing is copied. Thresholding is left to the user (a Threshold TOP before the operator). The pixels are read
// with the first row on top, as in PyEyesWeb.
//
// Difference from reading a 32-bit float image: a value of a floating-point TOP below 1/510 rounds to 0 in the 8-bit
// download, so it is background.
#pragma once
#include <cstddef>
#include <cstdint>
#include "ew/common/image.h"
#include "ew_td/plugin.h"

namespace ew_td {

class TopMask {
public:
    // The TOP of the `Top` parameter (the operators have no TOP input: a TOP cannot be wired into a CHOP).
    static const TD::OP_TOPInput* topOf(const TD::OP_Inputs* in) { return in->getParTOP("Top"); }

    explicit TopMask(const TD::OP_Inputs* in) {
        const TD::OP_TOPInput* top = topOf(in);
        require(top != nullptr, "no TOP: set the Top parameter to the silhouette");
        TD::OP_TOPInputDownloadOptions options;
        options.verticalFlip = true;
        options.pixelFormat = TD::OP_PixelFormat::Mono8Fixed;
        download_ = top->downloadTexture(options, nullptr);
        require(static_cast<bool>(download_), "the TOP could not be read");
        const TD::OP_TextureDesc& desc = download_->textureDesc;
        const int width = static_cast<int>(desc.width), height = static_cast<int>(desc.height);
        require(desc.texDim == TD::OP_TexDim::e2D && width > 0 && height > 0, "the TOP is not a 2D image");
        require(desc.pixelFormat == options.pixelFormat, "the TOP was not given in the requested pixel format");
        const std::size_t count = static_cast<std::size_t>(width) * static_cast<std::size_t>(height);
        const std::uint8_t* pixels = static_cast<const std::uint8_t*>(download_->getData());
        require(pixels != nullptr && download_->size >= count, "the TOP has no pixel data");
        view_ = ew::ImageView{pixels, width, height, 1, 0};  // the downloaded bytes are the mask: no copy
    }

    // Valid while this object lives.
    const ew::ImageView& view() const { return view_; }

private:
    TD::OP_SmartRef<TD::OP_TOPDownloadResult> download_;
    ew::ImageView view_;
};

}  // namespace ew_td
