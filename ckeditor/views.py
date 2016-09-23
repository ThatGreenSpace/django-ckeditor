from datetime import datetime
import os
import sys

from django.conf import settings
from django.core.files.storage import default_storage
from django.views.decorators.csrf import csrf_exempt
from django.views import generic
from django.http import HttpResponse
from django.shortcuts import render_to_response
from django.template import RequestContext

from ckeditor import image_processing
from ckeditor import utils


def get_upload_filename(upload_name, user, upload_directory=''):
    # If CKEDITOR_RESTRICT_BY_USER is True upload file to user specific path.
    if getattr(settings, 'CKEDITOR_RESTRICT_BY_USER', False):
        user_path = user.username
    else:
        user_path = ''

    # Complete upload path (upload_path + date_path).
    if upload_directory != '':
        upload_path = os.path.join(upload_directory)
    else:
        # Generate date based path to put uploaded file.
        date_path = datetime.now().strftime('%Y/%m/%d')
        upload_path = os.path.join(settings.CKEDITOR_UPLOAD_PATH, user_path, date_path)

    if getattr(settings, "CKEDITOR_UPLOAD_SLUGIFY_FILENAME", True):
        upload_name = utils.slugify_filename(upload_name)

    return default_storage.get_available_name(os.path.join(upload_path, upload_name))


class ImageUploadView(generic.View):
    http_method_names = ['post']

    def post(self, request, **kwargs):
        """
        Uploads a file and send back its URL to CKEditor.
        """
        # Get the uploaded file from request.
        upload = request.FILES['upload']

        #Verify that file is a valid image
        backend = image_processing.get_backend()
        try:
            backend.image_verify(upload)
        except utils.NotAnImageException:
            pass

        # Open output file in which to store upload.
        if request.GET.get('upload_directory', None):
            upload_filename = get_upload_filename(upload.name, request.user, request.GET.get('upload_directory'))
        else:
            upload_filename = get_upload_filename(upload.name, request.user)
        saved_path = default_storage.save(upload_filename, upload)

        if backend.should_create_thumbnail(saved_path):
            backend.create_thumbnail(saved_path)

        url = utils.get_media_url(saved_path)

        # Respond with Javascript sending ckeditor upload url.
        return HttpResponse("""
        <script type='text/javascript'>
            window.parent.CKEDITOR.tools.callFunction({0}, '{1}');
        </script>""".format(request.GET['CKEditorFuncNum'], url))

upload = csrf_exempt(ImageUploadView.as_view())


def get_image_files(user=None, path=''):
    """
    Recursively walks all dirs under upload dir and generates a list of
    full paths for each file found.
    """
    # If a user is provided and CKEDITOR_RESTRICT_BY_USER is True,
    # limit images to user specific path, but not for superusers.
    STORAGE_DIRECTORIES = 0
    STORAGE_FILES = 1

    if path != '':
        browse_path = os.path.join(path)
    else:
        restrict = getattr(settings, 'CKEDITOR_RESTRICT_BY_USER', False)
        if user and not user.is_superuser and restrict:
            user_path = user.username
        else:
            user_path = ''
        browse_path = os.path.join(settings.CKEDITOR_UPLOAD_PATH, user_path, path)

    try:
        storage_list = default_storage.listdir(browse_path)
    except NotImplementedError:
        return
    except OSError:
        return

    for filename in storage_list[STORAGE_FILES]:
        if os.path.splitext(filename)[0].endswith('_thumb') or os.path.basename(filename).startswith('.'):
            continue
        filename = os.path.join(browse_path, filename)
        yield filename

    for directory in storage_list[STORAGE_DIRECTORIES]:
        if directory.startswith('.'):
            continue
        directory_path = os.path.join(path, directory)
        for element in get_image_files(user=user, path=directory_path):
            yield element


def get_files_browse_urls(user=None, browse_directory=None):
    """
    Recursively walks all dirs under upload dir and generates a list of
    thumbnail and full image URL's for each file found.
    """
    files = []
    if browse_directory and browse_directory != '':
        image_files = get_image_files(user=user, path=browse_directory)
    else:
        image_files = get_image_files(user=user)

    for filename in image_files:
        src = utils.get_media_url(filename)
        visible_filename = None
        if getattr(settings, 'CKEDITOR_IMAGE_BACKEND', None):
            if is_image(src):
                thumb = utils.get_media_url(utils.get_thumb_filename(filename))
            else:
                thumb = utils.get_icon_filename(filename)
                visible_filename = os.path.split(filename)[1]
                if len(visible_filename) > 20:
                    visible_filename = visible_filename[0:19] + '...'
        else:
            thumb = src
        files.append({
            'thumb': thumb,
            'src': src,
            'is_image': is_image(src),
            'visible_filename': visible_filename,
        })

    return files


def is_image(path):
    ext = path.split('.')[-1].lower()
    return ext in ['jpg', 'jpeg', 'png', 'gif']


def browse(request):
    context = RequestContext(request, {
        'files': get_files_browse_urls(request.user, request.GET.get('browse_directory', None)),
    })
    return render_to_response('browse.html', context)
