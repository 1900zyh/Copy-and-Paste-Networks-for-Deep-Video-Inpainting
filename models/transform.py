
import torch
import torchvision

import random
import numpy as np
from PIL import Image, ImageOps
from PIL import Image, ImageOps, ImageDraw,ImageFilter

class GroupRandomHorizontalFlip(object):
  """Randomly horizontally flips the given PIL.Image with a probability of 0.5
  """
  def __init__(self, is_flow=False):
    self.is_flow = is_flow

  def __call__(self, img_group, is_flow=False):
    v = random.random()
    if v < 0.5:
      ret = [img.transpose(Image.FLIP_LEFT_RIGHT) for img in img_group]
      if self.is_flow:
        for i in range(0, len(ret), 2):
          ret[i] = ImageOps.invert(ret[i])  # invert flow pixel values when flipping
      return ret
    else:
      return img_group

class GroupScale(object):
    """ Rescales the input PIL.Image to the given 'size'.
    'size' will be the size of the smaller edge.
    For example, if height > width, then image will be
    rescaled to (size * height / width, size)
    size: size of the smaller edge
    interpolation: Default: PIL.Image.BILINEAR
    """
    def __init__(self, size, interpolation=Image.BILINEAR):
      self.worker = torchvision.transforms.Resize(size, interpolation)

    def __call__(self, img_group):
      return [self.worker(img) for img in img_group]

class Stack(object):
  def __init__(self, roll=False):
    self.roll = roll

  def __call__(self, img_group):
    mode = img_group[0].mode
    if mode == '1':
      img_group = [img.convert('L') for img in img_group]
      mode = 'L'
    if mode == 'L':
      return np.stack([np.expand_dims(x, 2) for x in img_group], axis=2)
    elif mode == 'RGB':
      if self.roll:
        return np.stack([np.array(x)[:, :, ::-1] for x in img_group], axis=2)
      else:
        return np.stack(img_group, axis=2)
    else:
      raise NotImplementedError(f"Image mode {mode}")

class ToTorchFormatTensor(object):
  """ Converts a PIL.Image (RGB) or numpy.ndarray (H x W x C) in the range [0, 255]
  to a torch.FloatTensor of shape (C x H x W) in the range [0.0, 1.0] """
  def __init__(self, div=True):
    self.div = div

  def __call__(self, pic):
    if isinstance(pic, np.ndarray):
      # numpy img: [L, C, H, W]
      img = torch.from_numpy(pic).permute(2, 3, 0, 1).contiguous()
    else:
      # handle PIL Image
      img = torch.ByteTensor(torch.ByteStorage.from_buffer(pic.tobytes()))
      img = img.view(pic.size[1], pic.size[0], len(pic.mode))
      # put it from HWC to CHW format
      # yikes, this transpose takes 80% of the loading time/CPU
      img = img.transpose(0, 1).transpose(0, 2).contiguous()
    img = img.float().div(255) if self.div else img.float()
    return img


def get_video_masks_by_moving_random_stroke(
    video_len, imageWidth=424, imageHeight=240, nStroke=3,
    nVertexBound=[5, 20], maxHeadSpeed=15, maxHeadAcceleration=(15, 3.14),
    brushWidthBound=(30, 50), boarderGap=50, nMovePointRatio=0.5, maxPiontMove=10,
    maxLineAcceleration=(5,0.5), maxInitSpeed=10
):
    '''
    Get video masks by random strokes which move randomly between each
    frame, including the whole stroke and its control points
    Parameters
    ----------
        imageWidth: Image width
        imageHeight: Image height
        nStroke: Number of drawed lines
        nVertexBound: Lower/upper bound of number of control points for each line
        maxHeadSpeed: Max head speed when creating control points
        maxHeadAcceleration: Max acceleration applying on the current head point (
            a head point and its velosity decides the next point)
        brushWidthBound (min, max): Bound of width for each stroke
        boarderGap: The minimum gap between image boarder and drawed lines
        nMovePointRatio: The ratio of control points to move for next frames
        maxPiontMove: The magnitude of movement for control points for next frames
        maxLineAcceleration: The magnitude of acceleration for the whole line
    Examples
    ----------
        object_like_setting = {
            "nVertexBound": [5, 20],
            "maxHeadSpeed": 15,
            "maxHeadAcceleration": (15, 3.14),
            "brushWidthBound": (30, 50),
            "nMovePointRatio": 0.5,
            "maxPiontMove": 10,
            "maxLineAcceleration": (5, 0.5),
            "boarderGap": 20,
            "maxInitSpeed": 10,
        }
        rand_curve_setting = {
            "nVertexBound": [10, 30],
            "maxHeadSpeed": 20,
            "maxHeadAcceleration": (15, 0.5),
            "brushWidthBound": (3, 10),
            "nMovePointRatio": 0.5,
            "maxPiontMove": 3,
            "maxLineAcceleration": (5, 0.5),
            "boarderGap": 20,
            "maxInitSpeed": 6
        }
        get_video_masks_by_moving_random_stroke(video_len=5, nStroke=3, **object_like_setting)
    '''
    assert(video_len >= 1)

    # Initilize a set of control points to draw the first mask
    mask = Image.new(mode='1', size=(imageWidth, imageHeight), color=0)
    control_points_set = []
    for _ in range(nStroke):
      brushWidth = np.random.randint(brushWidthBound[0], brushWidthBound[1])
      Xs, Ys, velocity = get_random_stroke_control_points(
        imageWidth=imageWidth, imageHeight=imageHeight,
        nVertexBound=nVertexBound, maxHeadSpeed=maxHeadSpeed,
        maxHeadAcceleration=maxHeadAcceleration, boarderGap=boarderGap,
        maxInitSpeed=maxInitSpeed)
      control_points_set.append((Xs, Ys, velocity, brushWidth))
      draw_mask_by_control_points(mask, Xs, Ys, brushWidth, fill=255)

    # Generate the following masks by randomly move strokes and their control points
    masks = [mask]
    for _ in range(video_len - 1):
      mask = Image.new(mode='1', size=(imageWidth, imageHeight), color=0)
      for j in range(len(control_points_set)):
        Xs, Ys, velocity, brushWidth = control_points_set[j]
        new_Xs, new_Ys, velocity = random_move_control_points(
          Xs, Ys, imageWidth, imageHeight, velocity, nMovePointRatio, maxPiontMove,
          maxLineAcceleration, boarderGap, maxInitSpeed)
        control_points_set[j] = (new_Xs, new_Ys, velocity, brushWidth)
      for Xs, Ys, velocity, brushWidth in control_points_set:
        draw_mask_by_control_points(mask, Xs, Ys, brushWidth, fill=255)
      masks.append(mask)
    return masks


def random_accelerate(velocity, maxAcceleration, dist='uniform'):
    speed, angle = velocity
    d_speed, d_angle = maxAcceleration

    if dist == 'uniform':
        speed += np.random.uniform(-d_speed, d_speed)
        angle += np.random.uniform(-d_angle, d_angle)
    elif dist == 'guassian':
        speed += np.random.normal(0, d_speed / 2)
        angle += np.random.normal(0, d_angle / 2)
    else:
        raise NotImplementedError(f'Distribution type {dist} is not supported.')

    return (speed, angle)


def random_move_control_points(Xs, Ys, imageWidth, imageHeight, lineVelocity, nMovePointRatio, maxPiontMove, maxLineAcceleration, boarderGap=15, maxInitSpeed=10):
    new_Xs = Xs.copy()
    new_Ys = Ys.copy()

    # move the whole line and accelerate
    speed, angle = lineVelocity
    new_velocity = False
    new_Xs += int(speed * np.cos(angle))
    new_Ys += int(speed * np.sin(angle))
    lineVelocity = random_accelerate(lineVelocity, maxLineAcceleration, dist='guassian')

    # choose points to move
    chosen = np.arange(len(Xs))
    np.random.shuffle(chosen)
    chosen = chosen[:int(len(Xs) * nMovePointRatio)]
    for i in chosen:
        new_Xs[i] += np.random.randint(-maxPiontMove, maxPiontMove)
        new_Ys[i] += np.random.randint(-maxPiontMove, maxPiontMove)
        if not new_velocity and ((new_Xs[i] > imageWidth) or (new_Xs[i] < 0) or (new_Ys[i]>imageHeight) or (new_Ys[i]<0)):
          new_velocity = True
        new_Xs[i] = np.clip(new_Xs[i], boarderGap, imageWidth - boarderGap)
        new_Ys[i] = np.clip(new_Ys[i], boarderGap, imageHeight - boarderGap)
    if new_velocity:
      lineVelocity = get_random_velocity(maxInitSpeed, dist='guassian')
    return new_Xs, new_Ys, lineVelocity


def get_random_stroke_control_points(
    imageWidth, imageHeight,
    nVertexBound=(10, 30), maxHeadSpeed=10, maxHeadAcceleration=(5, 0.5), boarderGap=20,
    maxInitSpeed=10
):
    '''
    Implementation the free-form training masks generating algorithm
    proposed by JIAHUI YU et al. in "Free-Form Image Inpainting with Gated Convolution"
    '''
    startX = np.random.randint(imageWidth)
    startY = np.random.randint(imageHeight)
    Xs = [startX]
    Ys = [startY]

    numVertex = np.random.randint(nVertexBound[0], nVertexBound[1])

    angle = np.random.uniform(0, 2 * np.pi)
    speed = np.random.uniform(0, maxHeadSpeed)

    for i in range(numVertex):
        speed, angle = random_accelerate((speed, angle), maxHeadAcceleration)
        speed = np.clip(speed, 0, maxHeadSpeed)

        nextX = startX + speed * np.sin(angle)
        nextY = startY + speed * np.cos(angle)

        if boarderGap is not None:
            nextX = np.clip(nextX, boarderGap, imageWidth - boarderGap)
            nextY = np.clip(nextY, boarderGap, imageHeight - boarderGap)

        startX, startY = nextX, nextY
        Xs.append(nextX)
        Ys.append(nextY)

    velocity = get_random_velocity(maxInitSpeed, dist='guassian')

    return np.array(Xs), np.array(Ys), velocity


def get_random_velocity(max_speed, dist='uniform'):
    if dist == 'uniform':
        speed = np.random.uniform(max_speed)
    elif dist == 'guassian':
        speed = np.abs(np.random.normal(0, max_speed / 2))
    else:
        raise NotImplementedError(f'Distribution type {dist} is not supported.')

    angle = np.random.uniform(0, 2 * np.pi)
    return (speed, angle)


def draw_mask_by_control_points(mask, Xs, Ys, brushWidth, fill=255):
    radius = brushWidth // 2 - 1
    for i in range(1, len(Xs)):
        draw = ImageDraw.Draw(mask)
        startX, startY = Xs[i - 1], Ys[i - 1]
        nextX, nextY = Xs[i], Ys[i]
        draw.line((startX, startY) + (nextX, nextY), fill=fill, width=brushWidth)
    for x, y in zip(Xs, Ys):
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill)
    return mask


# modified from https://github.com/naoto0804/pytorch-inpainting-with-partial-conv/blob/master/generate_data.py
def get_random_walk_mask(imageWidth=320, imageHeight=180, length=None):
    action_list = [[0, 1], [0, -1], [1, 0], [-1, 0]]
    canvas = np.zeros((imageHeight, imageWidth)).astype("i")
    if length is None:
        length = imageWidth * imageHeight
    x = random.randint(0, imageHeight - 1)
    y = random.randint(0, imageWidth - 1)
    x_list = []
    y_list = []
    for i in range(length):
        r = random.randint(0, len(action_list) - 1)
        x = np.clip(x + action_list[r][0], a_min=0, a_max=imageHeight - 1)
        y = np.clip(y + action_list[r][1], a_min=0, a_max=imageWidth - 1)
        x_list.append(x)
        y_list.append(y)
    canvas[np.array(x_list), np.array(y_list)] = 1
    return Image.fromarray(canvas * 255).convert('1')


def get_masked_ratio(mask):
    """
    Calculate the masked ratio.
    mask: Expected a binary PIL image, where 0 and 1 represent
          masked(invalid) and valid pixel values.
    """
    hist = mask.histogram()
    return hist[0] / np.prod(mask.size)