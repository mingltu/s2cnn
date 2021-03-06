#pylint: disable=C,R,E1101
import math
import torch
from torch.nn.parameter import Parameter
from torch.nn.modules import Module

from s2cnn.nn.soft.gpu.so3_fft import SO3_fft_real, SO3_ifft_real
from s2cnn.ops.so3_localft import so3_local_ft
from s2cnn.ops.gpu.so3_mm import SO3_mm

class SO3Convolution(Module):
    def __init__(self, nfeature_in, nfeature_out, b_in, b_out, grid):
        '''
        :param nfeature_in: number of input fearures
        :param nfeature_out: number of output features
        :param b_in: input bandwidth (precision of the input SOFT grid)
        :param b_out: output bandwidth
        :param grid: points of the SO(3) group defining the kernel, tuple of (alpha, beta, gamma)'s
        '''
        super(SO3Convolution, self).__init__()
        self.nfeature_in = nfeature_in
        self.nfeature_out = nfeature_out
        self.b_in = b_in
        self.b_out = b_out
        self.grid = grid
        self.kernel = Parameter(torch.Tensor(nfeature_in, nfeature_out, len(grid)))
        self.bias = Parameter(torch.Tensor(1, nfeature_out, 1, 1, 1))
        self.reset_parameters()

    def reset_parameters(self):
        # stdv = 1 / len(self.grid)**0.5 / self.nfeature_in**0.5 / self.b_out**1.5 * self.b_in**1.5
        stdv = 1. / math.sqrt(len(self.grid) * self.nfeature_in * (self.b_out ** 3.) / (self.b_in ** 3.))

        self.kernel.data.normal_(0, stdv)
        self.bias.data[:] = 0

    def forward(self, x): #pylint: disable=W
        '''
        :x:      [batch, feature_in,  beta, alpha, gamma]
        :return: [batch, feature_out, beta, alpha, gamma]
        '''
        assert x.size(1) == self.nfeature_in
        assert x.size(2) == 2 * self.b_in
        assert x.size(3) == 2 * self.b_in
        assert x.size(4) == 2 * self.b_in

        x = SO3_fft_real(b_out=self.b_out)(x) # [l * m * n, batch, feature_in, complex]
        y = so3_local_ft(self.kernel, self.b_out, self.grid) # [feature_in, feature_out, l * m * n, complex]
        y = y.transpose(0, 2) # [l * m * n, feature_out, feature_in, complex]
        y = y.transpose(1, 2) # [l * m * n, feature_in, feature_out, complex]
        y = y.contiguous()
        assert x.size(0) == y.size(0)
        assert x.size(2) == y.size(1)
        z = SO3_mm()(x, y) # [l * m * n, batch, feature_out, complex]
        assert z.size(0) == x.size(0)
        assert z.size(1) == x.size(1)
        assert z.size(2) == y.size(2)
        z = SO3_ifft_real()(z) # [batch, feature_out, beta, alpha, gamma]

        z.add_(self.bias.expand_as(z))

        return z


class SO3Shortcut(Module):
    '''
    Useful for ResNet
    '''
    def __init__(self, nfeature_in, nfeature_out, b_in, b_out):
        super(SO3Shortcut, self).__init__()
        assert b_out <= b_in

        if (nfeature_in != nfeature_out) or (b_in != b_out):
            self.conv = SO3Convolution(
                nfeature_in=nfeature_in, nfeature_out=nfeature_out, b_in=b_in, b_out=b_out,
                grid=((0, 0, 0), ))
        else:
            self.conv = None

    def forward(self, x): #pylint: disable=W
        '''
        :x:      [batch, feature_in,  beta, alpha, gamma]
        :return: [batch, feature_out, beta, alpha, gamma]
        '''
        if self.conv is not None:
            return self.conv(x)
        else:
            return x
