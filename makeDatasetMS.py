import os
import torch
from torch.utils.data import Dataset
from PIL import Image
import numpy as np
import glob
import random
from spatial_transforms import (Compose, ToTensor, CenterCrop, Scale, Normalize, MultiScaleCornerCrop,
                                RandomHorizontalFlip, Binary)


def gen_split(root_dir, stackSize, phase):
    RGB = []
    Labels = []
    Maps = []
    NumFrames = []
    root_dir = os.path.join(root_dir, 'processed_frames2') #GTEA61/processed_frames2/
    
    for dir_user in sorted(os.listdir(root_dir)): #S1/
        if dir_user=='.DS_Store': continue
        if (phase=='train') ^ (dir_user=="S2"):
            dir = os.path.join(root_dir, dir_user) #GTEA61/processed_frames2/S1/
            class_id=0
            
            for target in sorted(os.listdir(dir)): #close_choco/
                if target=='.DS_Store': continue
                dir1 = os.path.join(dir, target) #GTEA61/processed_frames2/S1/close_choco/
                
                insts = sorted(os.listdir(dir1)) #1/
                if insts != []:
                    for inst in insts:
                        if inst=='.DS_Store': continue
                        
                        inst_dir = os.path.join(dir1, inst+"/rgb") #GTEA61/processed_frames2/S1/close_choco/1/rgb/
                        numFrames = len(glob.glob1(inst_dir, '*.png'))
                        
                        if numFrames >= stackSize:
                            RGB.append(inst_dir)
                            Labels.append(class_id)
                            NumFrames.append(numFrames)
                            
                        inst_dir = os.path.join(dir1, inst+"/mmaps") #GTEA61/processed_frames2/S1/close_choco/1/mmaps/
                        
                        if numFrames >= stackSize:
                            Maps.append(inst_dir)
                class_id += 1
    return RGB, Maps, Labels, NumFrames 

class makeDataset(Dataset):
    def __init__(self, root_dir, spatial_transform=None, seqLen=20,
                 train=True, mulSeg=False, numSeg=1, fmt='.png',phase='train', regressor=False):

        self.images, self.maps, self.labels, self.numFrames = gen_split(root_dir, 5,phase)
        normalize = Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
        self.spatial_transform0 = spatial_transform
        self.spatial_rgb= Compose([self.spatial_transform0, ToTensor(), normalize])
        
        if not(regressor):
            self.spatial_transform_map = Compose([self.spatial_transform0, Scale(7), ToTensor(), Binary(0.4)])
        else:
            self.spatial_transform_map = Compose([self.spatial_transform0, Scale(7), ToTensor()])
               
        
        self.train = train
        self.mulSeg = mulSeg
        self.numSeg = numSeg
        self.seqLen = seqLen
        self.fmt = fmt

    def __len__(self):
        return len(self.images)

    def __getitem__(self, idx):
        vid_name = self.images[idx]
        label = self.labels[idx]
        map_name = self.maps[idx]

        numFrame = self.numFrames[idx]
        inpSeq = []
        mapSeq = []
        self.spatial_transform0.randomize_parameters()
        for i in np.linspace(1, numFrame, self.seqLen, endpoint=False):
            fl_name = vid_name + '/' + 'rgb' + str(int(np.floor(i))).zfill(4) + self.fmt
            img = Image.open(fl_name)
            flag=1
            j=i
            while(flag):
                
                maps_name = map_name + '/' + 'map' + str(int(np.floor(j))).zfill(4) + self.fmt
                try:
                    mappa = Image.open(maps_name)
                    flag=0
                except:
                    if j<=i:
                        j= 2*i-j+1 #j=i --> j=i +1 ; j=i-1 j-i=-1 --> j=i-(-1)+1
                    else:
                        j= 2*i-j #j=i+1 j-i=1 --> j=i-1
                    continue

            inpSeq.append(self.spatial_rgb(img.convert('RGB')))
            mapSeq.append(self.spatial_transform_map(mappa.convert('L'))) #Grayscale
        inpSeq = torch.stack(inpSeq, 0)
        mapSeq = torch.stack(mapSeq, 0)
        return inpSeq, mapSeq, label
