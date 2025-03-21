import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
from nystrom_attention import NystromAttention


class TransLayer(nn.Module):

    def __init__(self, norm_layer=nn.LayerNorm, dim=512):
        super().__init__()
        self.norm = norm_layer(dim)
        self.attn = NystromAttention(
            dim = dim,
            dim_head = dim//8,
            heads = 8,
            num_landmarks = dim//2,    # number of landmarks
            pinv_iterations = 6,    # number of moore-penrose iterations for approximating pinverse. 6 was recommended by the paper
            residual = True,         # whether to do an extra residual with the value or not. supposedly faster convergence if turned on
            dropout=0.1
        )

    def forward(self, x, mask):
        x = x + self.attn(self.norm(x), mask)

        return x


class PPEG(nn.Module):
    def __init__(self, dim=512):
        super(PPEG, self).__init__()
        self.proj = nn.Conv2d(dim, dim, 7, 1, 7//2, groups=dim)
        self.proj1 = nn.Conv2d(dim, dim, 5, 1, 5//2, groups=dim)
        self.proj2 = nn.Conv2d(dim, dim, 3, 1, 3//2, groups=dim)

    def forward(self, x, H, W):
        B, _, C = x.shape
        cls_token, feat_token = x[:, 0], x[:, 1:]
        cnn_feat = feat_token.transpose(1, 2).view(B, C, H, W)
        x = self.proj(cnn_feat)+cnn_feat+self.proj1(cnn_feat)+self.proj2(cnn_feat)
        x = x.flatten(2).transpose(1, 2)
        x = torch.cat((cls_token.unsqueeze(1), x), dim=1)
        return x


class TransMIL(nn.Module):
    def __init__(self,
                 input_dim=1024,
                 d_model=512,
                 output_dim=4):
        super(TransMIL, self).__init__()
        self.pos_layer = PPEG(dim=d_model)
        self._fc1 = nn.Sequential(nn.Linear(input_dim, d_model), nn.ReLU())
        self.cls_token = nn.Parameter(torch.randn(1, 1, d_model))
        self.output_dim = output_dim
        self.layer1 = TransLayer(dim=d_model)
        self.layer2 = TransLayer(dim=d_model)
        self.norm = nn.LayerNorm(d_model)
        self._fc2 = nn.Linear(d_model, self.output_dim)

        
        cls_mask = torch.zeros([1,1])
        self.register_buffer("cls_mask", cls_mask)



    def forward(self, data):

        h = data['patch_features']
        mask = data['mask']
        # h = h[~mask.bool()].unsqueeze(0)

        h = self._fc1(h) #[B, n, 512]
        
        #---->pad
        H = h.shape[1]
        _H, _W = int(np.ceil(np.sqrt(H))), int(np.ceil(np.sqrt(H)))
        add_length = _H * _W - H
        h = torch.cat([h, h[:,:add_length,:]],dim = 1) #[B, N, 512]
        mask = torch.cat([mask, mask[:,:add_length]],dim = 1)

        #---->cls_token
        B = h.shape[0]
        cls_tokens = self.cls_token.expand(B, -1, -1)
        h = torch.cat((cls_tokens, h), dim=1)

        #---->Translayer x1
        mask = torch.cat([self.cls_mask, mask], dim=-1)
        mask = 1-mask
        mask = mask.bool()
        
        h = self.layer1(h, mask = mask) #[B, N, 512]

        #---->PPEG
        h = self.pos_layer(h, _H, _W) #[B, N, 512]
        
        #---->Translayer x2
        h = self.layer2(h, mask = mask) #[B, N, 512]

        #---->cls_token
        h = self.norm(h)[:,0]

        #---->predict
        logits = self._fc2(h) #[B, n_classes]
        # Y_hat = torch.argmax(logits, dim=1)
        # Y_prob = F.softmax(logits, dim = 1)
        # results_dict = {'logits': logits, 'Y_prob': Y_prob, 'Y_hat': Y_hat}
        # return results_dict
        return {'output':logits}

if __name__ == "__main__":
    data = torch.randn((1, 6000, 1024)).cuda()
    model = TransMIL(output_dim=2).cuda()
    print(model.eval())
    results_dict = model(data = data)
    print(results_dict)